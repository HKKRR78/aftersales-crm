"""Reconcile exact PDD native sale lines with complete official custom exports.

Reuses the company's canonical CSV/ZIP reader and identity/query validation.
The reconciliation report is deliberately not accepted as a sales source.
Creation-window manifests certify their original orders, not paid-day coverage.
"""
from __future__ import annotations
import argparse,hashlib,importlib.util,json,os
from datetime import date,datetime,timedelta
from pathlib import Path
from crm_report_model import canonical,text
from crm_native_snapshot import source_datetime


def company_reader():
    root=Path(os.environ['PDD_PROJECT_ROOT'])
    spec=importlib.util.spec_from_file_location('crm_official_pdd_reader',root/'scripts/pdd_order_report_ingest.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observed_time(reader,log,start,end):
    queries=[v['query'] for v in reader.evidence(log,start,end).values() if v.get('query')]
    if not queries:raise ValueError('PDD source query timestamps missing')
    times=[source_datetime(q.get('time')) for q in queries]
    if any(t is None for t in times):raise ValueError('PDD source query timestamp missing')
    return max(times)


def read_manifest(row,reader):
    path=Path(row['manifest_path']);log=Path(row['source_log_path'])
    if sha256(path)!=row['manifest_sha256'] or sha256(log)!=row['source_log_sha256']:
        raise ValueError('PDD original manifest or source query log changed')
    manifest=json.loads(path.read_bytes())
    start=date.fromisoformat(manifest['period_start']);end=date.fromisoformat(manifest['period_end'])
    if str(row['period_start'])!=str(start) or str(row['period_end'])!=str(end):
        raise ValueError('PDD manifest registered scope changed')
    if (manifest.get('report_type')!='订单-自定义报表' or manifest.get('status') not in ('VALIDATED','COMMITTED')
        or manifest.get('duplicate')!=0):raise ValueError('not a validated native PDD order export')
    shops=manifest.get('shop_results') or []
    if not shops or manifest['shops']!=len(shops) or len({s['mall_id'] for s in shops})!=len(shops):
        raise ValueError('PDD manifest shop set is not unique or complete')
    ev=reader.evidence(log,start,end);totals=[0,0,0,0];seen=set()
    if str(row['observed_at'])!=str(observed_time(reader,log,start,end)):
        raise ValueError('PDD original observation time changed')
    for shop in shops:
        shop_name=shop['shop_name'];mall=text(shop['mall_id']);source=ev.get(shop_name,{})
        identity=source.get('identity',{});query=source.get('query',{})
        if (text(identity.get('mallId'))!=mall or identity.get('source')!='localStorage.new_userinfo.mallId'
            or reader.SHOP_IDS.get(shop_name)!=mall or query.get('count') is None):
            raise ValueError('PDD original stable shop or exact query missing')
        count=int(query['count'])
        if shop.get('status')=='PASS_ZERO' and count==0 and not shop.get('source_file'):
            if any(shop.get(k)!=0 for k in ('platform_main_orders','file_rows','file_main_orders','business_keys','duplicate')):
                raise ValueError('PDD empty source count inconsistent')
            continue
        file=Path(shop['source_file'])
        if shop.get('status')!='PASS' or sha256(file)!=shop['sha256'] or not source.get('download'):
            raise ValueError('PDD original download or hash missing')
        _,raw=reader.file_rows(file)
        native=[reader.payload('custom',file,n,item,shop_name,'crm-proof',start,end) for n,item in enumerate(raw,2)]
        keys={r['business_key_v2'] for r in native};orders={r['订单号'] for r in native}
        if len(keys)!=len(native) or seen & keys:raise ValueError('duplicate original PDD sales identity')
        if (len(orders)!=count or shop['platform_main_orders']!=count or shop['file_rows']!=len(native)
            or shop['file_main_orders']!=len(orders) or shop['business_keys']!=len(keys) or shop['duplicate']!=0):
            raise ValueError('PDD official page/file/key counts disagree')
        seen.update(keys)
        totals=[a+b for a,b in zip(totals,[count,len(native),len(orders),len(keys)])]
        for n,item in enumerate(native,2):
            yield item,dict(manifest_sha256=row['manifest_sha256'],file=str(file),sha256=shop['sha256'],row=n,
                           observed_at=str(source_datetime(query['time'])),source_log_sha256=row['source_log_sha256'])
    if totals!=[manifest[k] for k in ('platform_main_orders','file_rows','file_main_orders','business_keys')]:
        raise ValueError('PDD manifest aggregate counts disagree')


def reconcile(sales,original,proof):
    # Native PDD custom export has one sales line per order; the complete file
    # has already rejected repeated order business keys, including multi-SKUs.
    if len(sales)!=1:return False
    sale=sales[0]
    if (sale['platform']!='pinduoduo' or sale['shop_key']!=text(original['mall_id'])
        or sale['order_no']!=text(original['订单号']) or sale['product_id']!=text(original['商品id'])
        or sale['native_sku_id']!=text(original['样式ID']) or sale['code']!=text(original['商家编码-规格维度'])
        or sale['quantity']!=original['商品数量(件)']):return False
    sale['original_order_complete']=True
    sale['evidence']['original_order_proof']={**proof,'original_line_count':1}
    return True


def apply_original_file_proofs(conn,orders):
    from crm_sales_sources import query
    rows=query(conn,'SELECT * FROM crm_pdd_order_manifest ORDER BY observed_at DESC,manifest_sha256 DESC')
    if not rows:return
    reader=company_reader();seen=set()
    for row in rows:
        # Fully consume the generator before mutating matches, including its
        # final total check. An invalid file never leaves partial attributions.
        candidates={}
        for original,proof in read_manifest(row,reader):
            key=('pinduoduo',text(original['mall_id']),text(original['订单号']))
            if key in orders and key not in seen:candidates[key]=(original,proof)
        for key,(original,proof) in candidates.items():
            seen.add(key)
            reconcile(list(orders[key].values()),original,proof)


if __name__=='__main__':
    from crm_schema import connect_mysql
    from crm_report_schema import ensure_report_schema
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--source-log',type=Path,required=True)
    args=p.parse_args();args.manifest=args.manifest.resolve();args.source_log=args.source_log.resolve()
    manifest=json.loads(args.manifest.read_bytes())
    reader=company_reader()
    row=dict(manifest_sha256=sha256(args.manifest),manifest_path=str(args.manifest),source_log_path=str(args.source_log),
             source_log_sha256=sha256(args.source_log),period_start=manifest['period_start'],period_end=manifest['period_end'],
             observed_at=observed_time(reader,args.source_log,date.fromisoformat(manifest['period_start']),date.fromisoformat(manifest['period_end'])))
    count=sum(1 for _ in read_manifest(row,reader))
    conn=connect_mysql()
    try:
        ensure_report_schema(conn)
        with conn.cursor() as cur:
            cur.execute('INSERT IGNORE INTO crm_pdd_order_manifest ('+','.join(row)+') VALUES('+','.join(['%s']*len(row))+')',list(row.values()))
        conn.commit();print(canonical({'registered_original_lines':count,'manifest_sha256':row['manifest_sha256']}))
    finally:conn.close()
