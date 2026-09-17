"""Pin retained company WeChat exports with their original API evidence.

This proves an individual original order version, not a complete payment day.
It does not reload native orders, restore private fields, or alter source audits.
"""
import argparse,hashlib,json
from pathlib import Path
from crm_report_model import canonical,text


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exact_response_hashes(query):
    """A bounded detail read proves named orders, never a complete payment day."""
    path=Path(query['responses_path'])
    if sha256(path)!=query['responses_sha256']:raise ValueError('WeChat exact API responses changed')
    expected=query.get('order_ids') or []
    if not expected or len(expected)!=len(set(expected)):raise ValueError('exact source order set invalid')
    orders=set();records={}
    for line in path.read_text().splitlines():
        response=json.loads(line);order=response.get('response',{}).get('order',{});oid=text(order.get('order_id'))
        if (response.get('endpoint')!='/channels/ec/order/get' or not response.get('observed_at')
            or text(response.get('request',{}).get('order_id'))!=oid or oid not in expected or oid in orders):
            raise ValueError('WeChat exact response identity or version invalid')
        orders.add(oid);products=order.get('order_detail',{}).get('product_infos') or []
        if not products:raise ValueError('WeChat exact original lacks sales items')
        digest=hashlib.sha256(canonical(order).encode()).hexdigest()
        for product in products:
            key=(oid,text(product.get('product_id')),text(product.get('sku_id')))
            if not all(key) or key in records:raise ValueError('WeChat exact native sale duplicated or missing')
            records[key]=digest
    if orders!=set(expected):raise ValueError('WeChat exact source response missing')
    return records


def validate_evidence(evidence,shop,filename):
    if (evidence.get('platform_code')!='wechat_shop' or evidence.get('data_type')!='ORDER'
        or evidence.get('source_code')!='wechat_order_api' or text(evidence.get('platform_shop_id'))!=shop
        or Path(evidence.get('artifact_path','')).name!=filename):
        raise ValueError('WeChat original source or shop identity differs')
    query=evidence.get('query') or {};summary=evidence.get('summary') or {}
    if not all(query.get(k) is True for k in ('conditions_verified','result_refresh_verified')):
        raise ValueError('WeChat original API query was not verified')
    count=summary.get('candidate_unique_orders')
    if not isinstance(count,int) or count<0 or summary.get('detail_success_orders')!=count or summary.get('detail_failed_orders')!=0:
        raise ValueError('WeChat original API enumeration or detail retrieval is incomplete')
    if query.get('kind')=='EXACT_ORDER_IDS':
        records=exact_response_hashes(query)
        if len(records)!=summary.get('record_count') or len({key[0] for key in records})!=count:
            raise ValueError('WeChat exact response totals differ')
    return summary


def certify(original,evidence_path,shop):
    from crm_wechat_shipping import original_rows
    original=original.resolve();evidence_path=evidence_path.resolve()
    raw=evidence_path.read_bytes();evidence=json.loads(raw)
    summary=validate_evidence(evidence,shop,original.name)
    digest=sha256(original);records=original_rows(str(original),digest)
    if len(records)!=summary.get('record_count') or len({key[0] for key in records})!=summary['detail_success_orders']:
        raise ValueError('WeChat original API detail counts differ from retained exact sales lines')
    if evidence['query'].get('kind')=='EXACT_ORDER_IDS':
        expected=exact_response_hashes(evidence['query'])
        if {key:row['original_hash'] for key,row in records.items()}!=expected:
            raise ValueError('WeChat exact API and original workbook differ')
    return dict(shop_key=shop,file=str(original),sha256=digest,source_evidence=str(evidence_path),
                source_evidence_sha256=hashlib.sha256(raw).hexdigest(),source_rows=len(records),
                original_orders=summary['detail_success_orders'])


def registered_artifacts(conn,wanted):
    from crm_sales_sources import query
    for row in query(conn,'SELECT * FROM crm_wechat_order_artifact'):
        key=(row['shop_key'],row['source_filename'])
        if key not in wanted:continue
        proof=json.loads(row['evidence_json'])
        if hashlib.sha256(canonical(proof).encode()).hexdigest()!=row['proof_id']:
            raise ValueError('WeChat original artifact registration changed')
        if (proof['shop_key'],Path(proof['file']).name)!=key:
            raise ValueError('WeChat original registered shop or filename differs')
        if sha256(proof['source_evidence'])!=proof['source_evidence_sha256']:
            raise ValueError('WeChat original API evidence changed')
        validate_evidence(json.loads(Path(proof['source_evidence']).read_bytes()),key[0],key[1])
        # File bytes, exact native key and version are rechecked by the reader.
        yield key,{**proof,'artifact_proof_id':row['proof_id']}


def register(conn,original,evidence_path,shop):
    from crm_sales_sources import query
    if len(query(conn,"SELECT shop_sk FROM dim_shop WHERE platform_code='wechat_shop' AND platform_shop_id=%s",(shop,)))!=1:
        raise ValueError('WeChat stable native shop is not uniquely registered')
    proof=certify(original,evidence_path,shop)
    proof_id=hashlib.sha256(canonical(proof).encode()).hexdigest()
    with conn.cursor() as cur:
        cur.execute('INSERT IGNORE INTO crm_wechat_order_artifact VALUES(%s,%s,%s,%s)',
                    (proof_id,shop,original.name,canonical(proof)))
    return proof_id,proof


if __name__=='__main__':
    from crm_schema import connect_mysql
    from crm_report_schema import ensure_report_schema
    parser=argparse.ArgumentParser();parser.add_argument('--original',type=Path,required=True)
    parser.add_argument('--source-evidence',type=Path,required=True);parser.add_argument('--shop',required=True)
    args=parser.parse_args();conn=connect_mysql()
    try:
        ensure_report_schema(conn)
        proof_id,proof=register(conn,args.original,args.source_evidence,args.shop)
        conn.commit();print(canonical({'proof_id':proof_id,**proof}))
    finally:conn.rollback();conn.close()
