"""Certify a payment window by reconciling a complete original creation history.

A dated collection success or latest order date is not completeness evidence.
For the supported full-history API, check the official total, exact source
range/shop, preserved raw artifact and every current native sales line.
"""
from __future__ import annotations
import argparse,hashlib,json
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from crm_report_model import canonical,text

SHANGHAI=timezone(timedelta(hours=8))


def source_datetime(value):
    if value is None or text(value) in ('','null','-'):return None
    parsed=datetime.fromisoformat(text(value).replace('Z','+00:00'))
    parsed=parsed.astimezone(SHANGHAI).replace(tzinfo=None) if parsed.tzinfo else parsed
    return parsed.replace(microsecond=0)


def sales_signature(sales):
    vectors=[(s['line_key'],s['order_key'],s['code'],str(Decimal(str(s['quantity'])).normalize()),str(s['paid_at'] or ''),
              s['shipped'],s['sales_identity_known']) for s in sales]
    return hashlib.sha256(canonical(sorted(vectors)).encode()).hexdigest()


def validate_scope(manifest, meta, package_count):
    if manifest.get('source_code')!='xhs_order_api' or manifest.get('time_field')!='order_created_at' or manifest.get('api_time_type')!=3:
        raise ValueError('not an official original order creation query')
    if not all(manifest.get(k) is True for k in ['conditions_verified','result_refresh_verified','identity_verified']):
        raise ValueError('original query or shop was not verified')
    if manifest.get('contradiction_count')!=0:raise ValueError('original source contains payment contradictions')
    if not meta or not meta.get('opened_on'):raise ValueError('verified shop opening date missing')
    start=datetime.fromtimestamp(manifest['requested_start_ms']/1000,SHANGHAI).replace(tzinfo=None)
    end=datetime.fromtimestamp((manifest['requested_end_ms']+1)/1000,SHANGHAI).replace(tzinfo=None)
    observed=source_datetime(manifest['query_finished_at'])
    if start.time()!=datetime.min.time() or end.time()!=datetime.min.time() or start>=end:
        raise ValueError('original scope must contain complete Shanghai dates')
    if start.date()>meta['opened_on'] or observed is None or observed<end:
        raise ValueError('full creation history was not freshly read through the endpoint')
    if not all(manifest.get(k)==package_count for k in ['api_total','source_rows','unique_packages']):
        raise ValueError('original source total, pagination or unique count mismatch')
    return start,end,observed


def xhs_current_sales(conn,shops,shop,start,end):
    from crm_sales_sources import SOURCES,query,normalize_sale,verify_xhs_sales_rows
    spec=SOURCES['xiaohongshu']
    rows=query(conn,f"SELECT {spec['select']} FROM {spec['table']} WHERE p.shop_id=%s AND p.order_created_at>=%s AND p.order_created_at<%s",(shop,start,end))
    return [normalize_sale(r,'xiaohongshu',spec,shops) for r in verify_xhs_sales_rows(rows)]


def xhs_original_sales(packages,shops,shop,start,end):
    from crm_sales_sources import SOURCES,normalize_sale,verify_xhs_sales_rows
    rows=[];seen=set()
    for package in packages:
        package_id=text(package.get('packageId'))
        created=source_datetime(package.get('orderedAt'))
        if not package_id or package_id in seen or text(package.get('sellerId'))!=shop:
            raise ValueError('original package identity missing, duplicated or outside shop')
        if created is None or not start<=created<end:
            raise ValueError('original package creation time outside verified range')
        seen.add(package_id)
        items=package.get('skus')
        if not isinstance(items,list) or not items:raise ValueError('original package lacks sales items')
        for item in items:
            sku=text(item.get('skuId'))
            if not sku:raise ValueError('original native SKU missing')
            rows.append(dict(shop_id=shop,shop_name=None,order_no=package_id,sub_no=package_id,
                native_order_no=package.get('orderId'),native_sku_id=sku,product_id=sku,
                source_key=package_id+':'+sku,quantity=item.get('skuQuantity'),
                paid_at=source_datetime(package.get('paidAt')),status=package.get('statusDesc'),
                shipped_flag=item.get('shipped'),sales_item_json=item,
                original_package_id=package.get('originalPackageId')))
    if len({r['source_key'] for r in rows})!=len(rows):raise ValueError('duplicate original package SKU')
    return [normalize_sale(r,'xiaohongshu',SOURCES['xiaohongshu'],shops) for r in verify_xhs_sales_rows(rows)]


def certify_xhs(conn,manifest_path,original_path):
    from crm_sales_sources import Shops
    shops=Shops(conn)
    raw_manifest=manifest_path.read_bytes();manifest=json.loads(raw_manifest)
    raw_original=original_path.read_bytes()
    packages=[json.loads(line) for line in raw_original.splitlines() if line.strip()]
    shop=text(manifest.get('platform_shop_id'));meta=shops.by_key.get(('xiaohongshu',shop))
    start,end,observed=validate_scope(manifest,meta,len(packages))
    original=xhs_original_sales(packages,shops,shop,start,end)
    if manifest.get('item_rows')!=len(original):raise ValueError('original source item count mismatch')
    current=xhs_current_sales(conn,shops,shop,start,end)
    if sales_signature(original)!=sales_signature(current):
        by_key={s['line_key']:s for s in original};current_keys={s['line_key'] for s in current}
        diff=sum(s['line_key'] not in by_key or sales_signature([s])!=sales_signature([by_key[s['line_key']]]) for s in current)
        raise ValueError(f'native current rows differ from original history: current_changed_or_extra={diff},original_missing={len(set(by_key)-current_keys)}')
    proof=dict(platform='xiaohongshu',shop_key=shop,coverage_start=str(start.date()),coverage_end=str(end.date()),
        observed_at=str(observed),manifest_path=str(manifest_path),manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        original_path=str(original_path),original_sha256=hashlib.sha256(raw_original).hexdigest(),
        current_signature=sales_signature(current),package_count=len(packages),sales_line_count=len(current))
    return proof


def verified_snapshots(conn,end):
    """Recheck retained originals and native rows in the report's read snapshot.

    A previously certified file cannot bless a changed database, a later date,
    or a different shop. A failed newest proof never falls back to an old one.
    """
    from crm_sales_sources import query
    rows=query(conn,"""SELECT * FROM crm_native_snapshot_proof
        WHERE coverage_end >= %s ORDER BY observed_at DESC,proof_id DESC""",(end,))
    result={}
    for row in rows:
        key=row['platform'],row['shop_key']
        if key in result:continue
        expected=json.loads(row['evidence_json'])
        if hashlib.sha256(canonical(expected).encode()).hexdigest()!=row['proof_id']:
            raise ValueError('native snapshot evidence content changed')
        if row['platform']=='xiaohongshu':
            actual=certify_xhs(conn,Path(expected['manifest_path']),Path(expected['original_path']))
        elif row['platform']=='douyin' and expected.get('source_kind')=='official_paid_export':
            from crm_paid_snapshot import certify_douyin
            actual=certify_douyin(conn,Path(expected['manifest_path']))
        else:raise ValueError('unsupported native snapshot proof source')
        if canonical(actual)!=canonical(expected):raise ValueError('native snapshot evidence changed since certification')
        if (actual['platform'],actual['shop_key'])!=key:
            raise ValueError('native snapshot proof does not identify its registered shop')
        if any(str(row[field])!=actual[field] for field in ('coverage_start','coverage_end','observed_at')):
            raise ValueError('native snapshot scope metadata changed')
        result[key]={'proof_id':row['proof_id'],**actual}
    return result


if __name__=='__main__':
    from crm_schema import connect_mysql
    from crm_report_schema import ensure_report_schema
    p=argparse.ArgumentParser();p.add_argument('--platform',choices=['xiaohongshu','douyin'],required=True)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--original',type=Path)
    p.add_argument('--record',action='store_true');args=p.parse_args();conn=connect_mysql()
    try:
        if args.record:ensure_report_schema(conn)
        if args.platform=='xiaohongshu':
            if args.original is None:raise ValueError('original XHS packages required')
            proof=certify_xhs(conn,args.manifest,args.original)
        else:
            from crm_paid_snapshot import certify_douyin
            proof=certify_douyin(conn,args.manifest)
        if args.record:
            with conn.cursor() as cur:
                cur.execute('INSERT IGNORE INTO crm_native_snapshot_proof (proof_id,platform,shop_key,coverage_start,coverage_end,observed_at,evidence_json) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                    (hashlib.sha256(canonical(proof).encode()).hexdigest(),*(proof[k] for k in ['platform','shop_key','coverage_start','coverage_end','observed_at']),canonical(proof)))
            conn.commit()
        print(canonical(proof))
    finally:conn.rollback();conn.close()
