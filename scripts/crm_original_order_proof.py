"""Prove complete native order lines from the preserved original order API.

ERP processed sales and stockout components are never original-order proofs.
"""
from __future__ import annotations
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from crm_report_model import canonical,text


def original_from_evidence(row):
    """Verify both the preserved API envelope and the selected original row."""
    path=Path(row['artifact_path'])
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=path.stem:
        raise ValueError('original order artifact hash changed')
    envelope=json.loads(raw)
    if envelope.get('endpoint')!='vip_api_trade_query.php' or row['endpoint']!=envelope['endpoint']:
        raise ValueError('unsupported original order evidence endpoint')
    response=envelope.get('response',{})
    records=response.get('trade_list')
    if str(response.get('code'))!='0' or not isinstance(records,list) or len(records)!=response.get('total_count'):
        raise ValueError('incomplete original order evidence response')
    if text(envelope.get('request',{}).get('tid'))!=row['order_no']:
        raise ValueError('original order evidence request does not identify this order')
    original=json.loads(row['original_order_json'])
    digest=hashlib.sha256(canonical(original).encode()).hexdigest()
    if original is None:
        if digest!=row['content_hash'] or records:raise ValueError('empty original-order evidence is inconsistent')
        return None
    if digest!=row['content_hash'] or text(original.get('tid'))!=row['order_no']:
        raise ValueError('original order content changed')
    if sum(canonical(item)==canonical(original) for item in records)!=1:
        raise ValueError('original order is not unique in preserved response')
    return original


def reconcile_original_order(sales,original,proof):
    items=original.get('goods_list')
    if not sales or not isinstance(items,list) or not items:return False
    if len(items)!=int(original.get('order_count',-1)):return False
    if len({text(i.get('oid')) for i in items})!=len(items):return False
    if any(not text(i.get('oid')) or text(i.get('tid'))!=text(original.get('tid')) for i in items):return False
    # Original order contains every item, including cancelled lines. A partial
    # native extract or a transformed ERP bundle cannot certify the parent.
    matched=[];used=set()
    for item in items:
        candidates=[s for s in sales if (
            (s.get('native_sku_id') and s['native_sku_id']==text(item.get('spec_id'))
             and (s['platform']=='jd' or s['product_id']==text(item.get('goods_id'))))
            or (not s.get('native_sku_id') and text(item['oid']) in s['sub_keys']))
            and s['code']==text(item.get('spec_no'))
            and s['quantity']==Decimal(str(item.get('num')))
            and s['order_no']==text(original.get('tid'))]
        if len(candidates)!=1 or candidates[0]['line_key'] in used:return False
        sale=candidates[0];used.add(sale['line_key']);matched.append((sale,item))
    if used!={s['line_key'] for s in sales}:return False
    for sale,item in matched:
        sale['sub_keys'].add(text(item['oid']))
        sale['original_order_complete']=True
        sale['evidence']['original_order_proof']={**proof,'original_oid':text(item['oid']),
            'original_record_id':text(item.get('rec_id')),'original_line_count':len(items)}
    return True


def apply_original_order_proofs(conn,orders):
    from crm_sales_sources import query
    rows=query(conn,"""SELECT p.* FROM crm_original_order_proof p
      JOIN (SELECT platform,shop_key,order_no,MAX(observed_at) observed_at
        FROM crm_original_order_proof GROUP BY platform,shop_key,order_no) latest
      USING(platform,shop_key,order_no,observed_at)""")
    grouped={}
    for row in rows:
        key=(row['platform'],row['shop_key'],row['order_no'])
        if key in grouped and grouped[key]['content_hash']!=row['content_hash']:
            raise ValueError('conflicting simultaneous original order proofs')
        grouped[key]=row
    for key,row in grouped.items():
        sales=list(orders.get(key,{}).values())
        if sales:
            original=original_from_evidence(row)
            if original is not None:
                reconcile_original_order(sales,original,
                    {k:str(row[k]) for k in ('observed_at','endpoint','content_hash','artifact_path')})
