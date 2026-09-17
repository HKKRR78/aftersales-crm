#!/usr/bin/env python3
"""Read missing original-order proofs using the company's existing WDT client.

This adds evidence to CRM only; it never replaces platform sales or publishes a
report. Unsupported WDT platform routes remain with their native collectors.
"""
from __future__ import annotations
import argparse,hashlib,json,sys,time,uuid
from datetime import date,datetime,timedelta
from pathlib import Path
from crm_schema import connect_mysql
from crm_report_model import canonical,text
from crm_report_schema import ensure_report_schema
from crm_sales_sources import Shops,query,platform_code

PLATFORMS={'douyin','kuaishou','jd','wechat_shop','xiaohongshu','dongfangzhenxuan'}


def read_proofs(conn,client,end,artifacts,platforms,delay=2):
    from crm_report_build import current_facts
    from crm_report_scope import recent_release_scope
    from crm_sales_sources import match_native_orders
    shops=Shops(conn)
    routes={text(r['wdt_platform_id']):platform_code(r['canonical_platform_code']) for r in query(conn,'SELECT wdt_platform_id,canonical_platform_code FROM control_wdt_platform_route')}
    facts,_=current_facts(conn,end,date.fromisoformat(recent_release_scope(end)['requiredStart']))
    orders=match_native_orders(conn,shops,facts)
    targets=set()
    for fact in facts:
        shop=fact.get('_shop');order=text(fact.get('order_no'));sub=text(fact.get('sub_order_no'))
        if not shop or shop[0] not in platforms or not order:continue
        sales=list(orders.get((*shop,order),{}).values())
        uses_original=any(s['evidence'].get('original_order_proof',{}).get('endpoint')=='vip_api_trade_query.php' for s in sales)
        if not sub or uses_original or (shop[0]=='wechat_shop' and not any(sub in s['sub_keys'] for s in sales)):
            targets.add((*shop,order))
    targets=[dict(platform=p,shop_key=s,order_no=o) for p,s,o in sorted(targets)]
    artifacts.mkdir(parents=True,exist_ok=True)
    counts={'requested':len(targets),'verified_original_records':0,'empty':0}
    started=time.monotonic()
    proof_set=[]
    for n,target in enumerate(targets):
        key=target['platform'],target['shop_key'];shop=shops.by_key[key]
        erp_shop=text(shop.get('wdt_shop_id'))
        if not erp_shop:raise ValueError('official ERP shop ID missing: '+str(key))
        observed=datetime.now().replace(microsecond=0);start=observed-timedelta(days=1)
        endpoint='vip_api_trade_query.php'
        params=dict(tid=target['order_no'],shop_no=erp_shop,start_time=str(start),end_time=str(observed),page_no=0,page_size=100)
        response=client.execute(endpoint,params)
        if str(response.get('code'))!='0':raise RuntimeError('original-order API failed: '+str(response.get('code'))+' '+str(response.get('message')))
        records=response.get('trade_list')
        if not isinstance(records,list) or len(records)!=int(response.get('total_count',-1)):
            raise ValueError('original-order result is not a complete exact-order response')
        envelope=dict(endpoint=endpoint,request=params,observed_at=str(observed),response=response)
        digest=hashlib.sha256(canonical(envelope).encode()).hexdigest()
        path=artifacts/(digest+'.json');path.write_text(canonical(envelope),encoding='utf-8');path.chmod(0o600)
        candidates=[r for r in records if text(r.get('tid'))==text(target['order_no'])
                    and shops.resolve(routes.get(text(r.get('platform_id')),''),r.get('shop_no'),'')==key]
        if not records:
            counts['empty']+=1;original=None
        elif len(candidates)!=1:
            raise ValueError('original-order API returned conflicting order/shop identities')
        else:
            original=candidates[0]
            goods=original.get('goods_list')
            if not isinstance(goods,list) or len(goods)!=int(original.get('order_count',-1)):
                raise ValueError('original order has an incomplete item set')
            counts['verified_original_records']+=1
        # A latest exact empty result invalidates reuse of an older positive
        # original proof; it never deletes a sale or claims the order vanished.
        content=canonical(original);content_hash=hashlib.sha256(content.encode()).hexdigest()
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO crm_original_order_proof
                  (platform,shop_key,order_no,observed_at,endpoint,content_hash,artifact_path,original_order_json)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE
                  observed_at=VALUES(observed_at),artifact_path=VALUES(artifact_path)""",
                  (*key,target['order_no'],observed,endpoint,content_hash,str(path),content))
        proof_set.append({**target,'content_hash':content_hash,'artifact_path':str(path),'observed_at':str(observed)})
        print(canonical(dict(completed=n+1,remaining=len(targets)-n-1,platform=target['platform'],elapsed_seconds=round(time.monotonic()-started,2),**counts)),flush=True)
        if n+1<len(targets):time.sleep(delay)
    return {**counts,'platforms':sorted(platforms),'proofs':proof_set}


def collect_batch(conn,client,end,artifacts,platforms,delay=2):
    """Publish a complete proof set in one transaction, never a partial refresh."""
    source=query(conn,"SELECT batch_id,status,reconciliation_status FROM etl_crm_ticket_batches WHERE source_system='ticket_service' ORDER BY started_at DESC,batch_id DESC LIMIT 1")
    if not source or source[0]['status']!='published' or source[0]['reconciliation_status']!='approved':
        raise ValueError('latest ticket collection is not complete')
    source_id=source[0]['batch_id']
    batch='original_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    with conn.cursor() as cur:
        cur.execute("INSERT INTO crm_original_order_read_batch (batch_id,status,scope_end,source_batch_id,started_at,summary_json) VALUES(%s,'running',%s,%s,NOW(),%s)",
                    (batch,end,source_id,canonical({'platforms':sorted(platforms)})))
    conn.commit()
    try:
        result=read_proofs(conn,client,end,artifacts,platforms,delay)
        with conn.cursor() as cur:
            cur.execute("UPDATE crm_original_order_read_batch SET status='complete',completed_at=NOW(),summary_json=%s WHERE batch_id=%s",(canonical(result),batch))
        conn.commit()
        return {'batch_id':batch,**{k:v for k,v in result.items() if k!='proofs'}}
    except Exception as exc:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("UPDATE crm_original_order_read_batch SET status='failed',completed_at=NOW(),error_summary=%s WHERE batch_id=%s",(str(exc)[:1000],batch))
        conn.commit()
        raise


def require_complete_read(conn,end,source_id,expected_batch=None):
    rows=query(conn,'SELECT * FROM crm_original_order_read_batch ORDER BY started_at DESC,batch_id DESC LIMIT 1')
    if not rows or rows[0]['status']!='complete':raise ValueError('latest original-order read is incomplete or failed')
    row=rows[0];summary=json.loads(row['summary_json'])
    if (row['scope_end']!=end or row['source_batch_id']!=source_id
        or (expected_batch and expected_batch!=row['batch_id'])
        or set(summary.get('platforms',[]))!=PLATFORMS):
        raise ValueError('original-order read does not match this report source and scope')
    proofs=summary.get('proofs',[])
    if len(proofs)!=summary.get('requested') or len({(p['platform'],p['shop_key'],p['order_no']) for p in proofs})!=len(proofs):
        raise ValueError('original-order proof set is incomplete or duplicated')
    for proof in proofs:
        current=query(conn,'SELECT content_hash,artifact_path,observed_at FROM crm_original_order_proof WHERE platform=%s AND shop_key=%s AND order_no=%s ORDER BY observed_at DESC',
                      (proof['platform'],proof['shop_key'],proof['order_no']))
        if not current or any(str(current[0][k])!=proof[k] for k in ('content_hash','artifact_path','observed_at')):
            raise ValueError('original-order proof set changed after its complete read')
    return row['batch_id']


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--end',type=date.fromisoformat,required=True);p.add_argument('--artifacts',type=Path,required=True)
    p.add_argument('--company-source-root',type=Path,required=True)
    p.add_argument('--platform',action='append',choices=['douyin','kuaishou','jd','wechat_shop','xiaohongshu','dongfangzhenxuan'])
    args=p.parse_args();sys.path.insert(0,str(args.company_source_root))
    from dotenv import dotenv_values
    from etl.wdt_openapi import WdtOpenApiClient,WdtOpenApiConfig
    cfg=dotenv_values(args.company_source_root/'.env.solo')
    client=WdtOpenApiClient(WdtOpenApiConfig(sid=cfg['WDT_SID'],appkey=cfg['WDT_APPKEY'],appsecret=cfg['WDT_APPSECRET']),timeout=30,retries=3,retry_sleep=7)
    conn=connect_mysql()
    try:
        ensure_report_schema(conn)
        print(canonical(collect_batch(conn,client,args.end,args.artifacts,set(args.platform or PLATFORMS))))
    finally:conn.close()
