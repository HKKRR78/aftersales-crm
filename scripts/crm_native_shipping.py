"""Read shipment evidence from retained platform originals, without PII fields."""
from __future__ import annotations
import csv
import hashlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path


def source_text(value):
    value='' if value is None else str(value).strip()
    return value[2:-1] if value.startswith('="') and value.endswith('"') else value


def valid_ship_time(value):
    if not value:return False
    if isinstance(value,datetime):return value.year>=2000
    try:
        return datetime.fromisoformat(source_text(value).replace('/','-').replace('Z','+00:00')).year>=2000
    except ValueError:
        return False


def doudian_original_shipping(rows,already_shipped):
    """The canonical Douyin table omits the original export's 发货时间.

    Read each needed export once per period and require its stored SHA1 plus
    exact order, child, product, sales spec and purchase quantity to agree.
    No order title, buyer or address is retained in the derived evidence.
    """
    targets=defaultdict(list)
    for row in rows:
        if not already_shipped(row):targets[(row['source_file'],row.get('source_file_hash'))].append(row)
    for (filename,expected_hash),wanted in targets.items():
        path=Path(filename)
        if not expected_hash or not path.is_file():
            for row in wanted:row['shipping_source_reason']='native_original_file_unavailable'
            continue
        if path.suffix.lower()!='.csv':
            for row in wanted:row['shipping_source_reason']='native_original_format_not_verified'
            continue
        digest=hashlib.sha1()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        if digest.hexdigest()!=expected_hash:
            raise ValueError('native Douyin original file changed: '+str(path))
        before=path.stat()
        by_sub={source_text(r['sub_no']):r for r in wanted}
        matched=defaultdict(list)
        with path.open(encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream)
            required={'主订单编号','子订单编号','商品ID','商家编码','商品数量','发货时间'}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError('native Douyin original shipment columns missing: '+str(path))
            for ordinal,raw in enumerate(reader,start=2):
                sub=source_text(raw['子订单编号'])
                row=by_sub.get(sub)
                if not row:continue
                exact=(source_text(raw['主订单编号'])==source_text(row['order_no'])
                       and source_text(raw['商品ID'])==source_text(row['product_id'])
                       and source_text(raw['商家编码'])==source_text(row['code'])
                       and Decimal(source_text(raw['商品数量']))==Decimal(str(row['quantity'])))
                if exact:matched[sub].append((ordinal,source_text(raw['发货时间'])))
        after=path.stat()
        if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
            raise ValueError('native Douyin original file changed during reading')
        for row in wanted:
            matches=matched.get(source_text(row['sub_no']),[])
            if len(matches)!=1:
                row['shipping_source_reason']='native_original_line_not_unique'
            elif valid_ship_time(matches[0][1]):
                row['ship_time']=matches[0][1]
                row['native_shipping_proof']={'file':str(path),'sha1':expected_hash,
                    'row':matches[0][0],'field':'发货时间','value':matches[0][1]}
            else:row['shipping_source_reason']='native_original_ship_time_empty'


def wechat_product_shipped(row):
    """Shipment time and exact native product/SKU prove a historical shipment."""
    import json
    value=row.get('native_shipments')
    shipments=json.loads(value) if isinstance(value,str) else value
    if not isinstance(shipments,list):return False
    quantities={}
    for shipment in shipments:
        try:delivered=int(shipment.get('delivery_time') or 0)>0
        except (TypeError,ValueError):delivered=False
        if not delivered:continue
        shipment_key=(source_text(shipment.get('delivery_id')),source_text(shipment.get('waybill_id')))
        if not all(shipment_key):continue
        for product in shipment.get('product_infos',[]):
            if (source_text(product.get('product_id'))!=source_text(row['product_id'])
                or source_text(product.get('sku_id'))!=source_text(row['native_sku_id'])):continue
            quantity=Decimal(str(product.get('product_cnt') or 0))
            if shipment_key in quantities and quantities[shipment_key]!=quantity:return False
            quantities[shipment_key]=quantity
    return bool(quantities) and sum(quantities.values())==Decimal(str(row['quantity']))>0
