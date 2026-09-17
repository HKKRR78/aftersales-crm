"""Reconcile official payment exports with native current rows before coverage.

The source query, both native creation tabs, immutable original, and every
native sales line are evidence. A recent creation-date audit is insufficient.
"""
from __future__ import annotations
import csv,hashlib,json
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from crm_report_model import canonical,text

SHANGHAI=timezone(timedelta(hours=8))


def digest_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def timestamp(value):
    value=text(value)
    if value in ('','-','null'):return None
    return datetime.fromisoformat(value.replace('Z','+00:00')).replace(tzinfo=None)


def payment_chunks(start,end):
    """Keep native reconciliation queries bounded by one complete paid day."""
    day=start
    while day<end:
        stop=min(day+timedelta(days=1),end)
        yield day,stop
        day=stop


def validate_query(query,count,history,shop,report):
    if query.get('time_basis')!='PAID_AT' or text(query.get('shop_id'))!=shop or text(query.get('report_id'))!=report:
        raise ValueError('paid export identity or basis mismatch')
    source=query.get('query') or {}
    begin=source.get('pay_time_start');finish=source.get('pay_time_end')
    if not isinstance(begin,int) or not isinstance(finish,int):raise ValueError('official payment timestamps missing')
    start=datetime.fromtimestamp(begin,SHANGHAI).replace(tzinfo=None)
    end=datetime.fromtimestamp(finish+1,SHANGHAI).replace(tzinfo=None)
    if start>=end or start.time()!=datetime.min.time() or end.time()!=datetime.min.time():
        raise ValueError('payment query does not contain full Shanghai days')
    if source.get('create_time_start') or source.get('create_time_end') or source.get('report_type')!='STANDARD':
        raise ValueError('payment export restricted by another source period')
    allowed={'b_type','order','order_by','page','pageSize','sub_shop_id','stress_tag','pay_time_start','pay_time_end',
        'file_type','task_id','report_type','report_dimension','custom_export_fields','remember_choice','export_scene',
        'search_record_request','priority_delivery_search_record_request','verify_code','verify_type','verify_account','tab'}
    if set(source)-allowed:raise ValueError('unverified additional export filter')
    for field in ('sub_shop_id','stress_tag','report_dimension','custom_export_fields','search_record_request','priority_delivery_search_record_request'):
        if source.get(field):raise ValueError('filtered export cannot certify all sales')
    if source.get('b_type',-1)!=-1:raise ValueError('restricted export business type')
    for expected_tab,record in [('all',count),('history',history)]:
        if record.get('http_status')!=200 or record.get('code')!=0 or text(record.get('shop_id'))!=shop:
            raise ValueError('native order count identity or result unverified')
        q=record.get('query') or {}
        if q.get('tab')!=expected_tab or q.get('pay_time_start')!=begin or q.get('pay_time_end')!=finish:
            raise ValueError('native count does not cover the same payment period')
        if q.get('create_time_start') or q.get('create_time_end'):
            raise ValueError('native count clipped by creation date')
        if not isinstance(record.get('total'),int) or record['total']<0:
            raise ValueError('native order count missing')
    if history['total']!=0:raise ValueError('older-creation paid orders require their original export')
    if timestamp(query['verified_at']) is None:raise ValueError('source query observation missing')
    return start,end


def vector(row):
    from crm_sales_sources import native_shipped,UNSHIPPED_STATUSES
    quantity=row.get('quantity')
    if quantity is None or text(quantity)=='':raise ValueError('original purchase quantity missing')
    quantity=Decimal(str(quantity))
    if not quantity.is_finite() or quantity<0:raise ValueError('invalid original purchase quantity')
    shipped=native_shipped(row,'douyin')
    return (text(row['order_no']),text(row['sub_no']),text(row['product_id']),text(row['code']),
            str(quantity.normalize()),str(row['paid_at'] or ''),str(row['created_at'] or ''),
            text(row['status']),shipped,shipped or text(row['status']) in UNSHIPPED_STATUSES)


def read_douyin_original(path,start,end):
    result={}
    with path.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        required={'主订单编号','子订单编号','商品ID','商家编码','商品数量','支付完成时间','订单提交时间','订单状态','发货时间'}
        if not required.issubset(reader.fieldnames or []):raise ValueError('official CSV lacks required native fields')
        for raw in reader:
            row=dict(order_no=text(raw['主订单编号']),sub_no=text(raw['子订单编号']),product_id=text(raw['商品ID']),
                code=text(raw['商家编码']),quantity=text(raw['商品数量']),paid_at=timestamp(raw['支付完成时间']),
                created_at=timestamp(raw['订单提交时间']),status=text(raw['订单状态']),ship_time=timestamp(raw['发货时间']))
            key=row['sub_no']
            if not key or not row['order_no'] or key in result:raise ValueError('missing or duplicate original order line identity')
            if not row['paid_at'] or not start<=row['paid_at']<end:raise ValueError('original row outside payment period')
            if not row['created_at'] or row['created_at']>row['paid_at']:raise ValueError('original creation/payment chronology conflicts')
            result[key]=vector(row)
    return result


def certify_douyin(conn,manifest_path):
    from crm_sales_sources import SOURCES,query,doudian_original_shipping,native_shipped
    manifest_path=manifest_path.resolve();manifest=json.loads(manifest_path.read_text())
    if manifest.get('platform')!='douyin':raise ValueError('unsupported payment source')
    paths={};documents={}
    for kind in ('original','query','count','history_count'):
        path=Path(manifest[kind+'_path']).resolve();digest=digest_file(path)
        if digest!=manifest[kind+'_sha256']:raise ValueError('payment source artifact changed: '+kind)
        paths[kind]=str(path)
        if kind!='original':documents[kind]=json.loads(path.read_text())
    shop=text(manifest['shop_id']);report=text(manifest['report_id'])
    start,end=validate_query(documents['query'],documents['count'],documents['history_count'],shop,report)
    original=read_douyin_original(Path(paths['original']),start,end)
    if len({row[0] for row in original.values()})!=documents['count']['total']:
        raise ValueError('official total and original distinct orders differ')
    current=[]
    spec=SOURCES['douyin']
    for day,stop in payment_chunks(start,end):
        current.extend(query(conn,f"SELECT {spec['select']},order_created_at created_at FROM {spec['table']} WHERE shop_id=%s AND paid_date>=%s AND paid_date<%s",(shop,day,stop)))
    doudian_original_shipping(current,lambda r:native_shipped(r,'douyin'))
    keys=set();different=0
    for row in current:
        key=text(row['sub_no'])
        if not key or key in keys:raise ValueError('duplicate native payment line')
        keys.add(key)
        if original.get(key)!=vector(row):different+=1
    if different or keys!=set(original):
        raise ValueError(f'native payment rows differ from original: changed_or_extra={different},missing={len(set(original)-keys)}')
    observed=datetime.fromisoformat(documents['query']['verified_at'].replace('Z','+00:00')).astimezone(SHANGHAI).replace(tzinfo=None,microsecond=0)
    if observed<end:raise ValueError('payment source was read before the endpoint')
    return dict(platform='douyin',shop_key=shop,coverage_start=str(start.date()),coverage_end=str(end.date()),
        observed_at=str(observed),source_kind='official_paid_export',manifest_path=str(manifest_path),
        manifest_sha256=digest_file(manifest_path),artifacts={kind:{'path':path,'sha256':manifest[kind+'_sha256']} for kind,path in paths.items()},
        report_id=report,sales_line_count=len(original),order_count=documents['count']['total'],
        current_signature=hashlib.sha256(canonical(sorted(original.items())).encode()).hexdigest())
