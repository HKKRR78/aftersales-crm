"""Evaluate collection evidence without confusing creation and payment windows."""
from __future__ import annotations

from datetime import date, timedelta

from crm_sales_sources import query, text, platform_code
from crm_native_snapshot import verified_snapshots
from crm_report_model import canonical


def days(start, end):
    while start < end:
        yield start
        start += timedelta(days=1)


def date_value(value):
    return date.fromisoformat(str(value)[:10])


NATIVE_SOURCE_CODES={
    'douyin':'doudian_order_rpa','kuaishou':'kuaishou_order_rpa','pinduoduo':'pdd_order_custom_rpa',
    'jd':'jd_order_rpa','tmall':'tmall_order_rpa','taobao':'tmall_order_rpa',
    'wechat_shop':'wechat_order_api','xiaohongshu':'xhs_order_api',
    'dongfangzhenxuan':'eastbuy_order_rpa','tgc':'tgc_order_rpa',
}


def reporting_shops(conn,shops,start,end):
    """Supplier login accounts locate exports; TGC storefronts own sales.

    Release scope comes from the source contracts and their effective dates,
    rather than every historical dim_shop row. Include every contracted
    storefront, even one with no current issues or sales, and every additional
    TGC storefront actually present in native orders. An unknown storefront
    remains a gap instead of disappearing from totals.
    """
    scope_rows=query(conn,"""SELECT c.platform_code,s.platform_shop_id,s.shop_name_observed,
        s.coverage_role,s.collection_status,s.effective_start,s.effective_end,c.source_code
        FROM control_data_source_shop_scope s
        JOIN control_data_source_contract c ON c.contract_id=s.contract_id
        WHERE UPPER(c.data_type)='ORDER' AND s.coverage_role='PRIMARY'
          AND s.effective_start<%s AND s.effective_end>=%s""",(end,start))
    result={};scoped_platforms=set()
    for row in scope_rows:
        platform=platform_code(row['platform_code']);shop=text(row['platform_shop_id'])
        if not shop or row['source_code']!=NATIVE_SOURCE_CODES.get(platform):continue
        scoped_platforms.add(platform);key=(platform,shop);registered=shops.by_key.get(key,{})
        result[key]={**registered,
            'shop_name_current':registered.get('shop_name_current') or row['shop_name_observed'] or shop,
            'opened_on':registered.get('opened_on'),'is_active':registered.get('is_active',1),
            'registry_effective_end':registered.get('effective_end'),
            'effective_start':row['effective_start'],'effective_end':row['effective_end'],
            'collection_status':row.get('collection_status'),'scope_basis':'primary_source_contract'}
    # A contract without any registered shop is itself an unresolved scope.
    # Retain the platform's master-data identities so it cannot vanish from
    # coverage merely because its control scope is incomplete.
    for platform in NATIVE_SOURCE_CODES:
        if platform in scoped_platforms:continue
        for key,meta in shops.by_key.items():
            if key[0]==platform:
                result[key]={**meta,'scope_basis':'registry_without_contract_scope'}
    retired=[key for key,meta in result.items() if key[0]=='tmall' and meta.get('is_active')==0
             and result.get(('taobao',key[1]),{}).get('is_active')==1]
    if retired:
        # The shared Taobao/Tmall collector has an explicit master-data
        # reassignment. A retired, superseded identity is not a second shop.
        # Neither an inactive flag alone nor a matching name proves this.
        aliases=query(conn,"""SELECT a.source_shop_id,a.shop_sk,a.updated_at FROM dim_shop_alias a
            JOIN dim_shop s ON s.shop_sk=a.shop_sk
            WHERE a.source_system='tmall_ods' AND s.platform_code='taobao' AND s.is_active=1
              AND a.effective_start<=%s AND a.effective_end>=%s""",(start,end))
        for old_key in retired:
            old=result[old_key];current_key=('taobao',old_key[1]);current=result[current_key]
            matching=[a for a in aliases if text(a['source_shop_id'])==old_key[1]
                      and a['shop_sk']==current.get('shop_sk')
                      and str(a['updated_at'])==str(old.get('registry_effective_end'))]
            if len(matching)!=1:continue
            remaining=query(conn,"""SELECT sub_order_id FROM ods_tmall_sales_detail
                WHERE platform_code='tmall' AND shop_id=%s AND paid_at>=%s AND paid_at<%s LIMIT 1""",
                (old_key[1],start,end))
            if remaining:raise ValueError('retired Tmall identity still owns native sales in the release scope')
            result[current_key]={**current,'retired_registry_identity':{
                'platform':old_key[0],'shop_key':old_key[1],'shop_sk':old['shop_sk'],
                'retired_at':str(old['registry_effective_end']),'canonical_shop_sk':current['shop_sk'],
                'basis':'explicit_tmall_ods_alias_reassignment'}}
            del result[old_key]
    if not any(platform=='tgc' for platform,_ in result):return result
    result={key:meta for key,meta in result.items() if key[0]!='tgc'}
    scopes=query(conn,"""SELECT s.platform_shop_id,s.shop_name_observed,s.effective_start,s.effective_end FROM control_data_source_shop_scope s
        JOIN control_data_source_contract c ON c.contract_id=s.contract_id
        WHERE c.source_code='tgc_order_rpa' AND UPPER(c.data_type)='ORDER' AND s.coverage_role='PRIMARY'
          AND s.effective_start<%s AND s.effective_end>=%s""",(end,start))
    observed=query(conn,"""SELECT DISTINCT shop_id platform_shop_id FROM ods_tgc_order_detail
        WHERE order_paid_time>=%s AND order_paid_time<%s""",(start,end))
    registered={text(r['platform_shop_id']):r for r in scopes}
    for shop in sorted(set(registered)|{text(r['platform_shop_id']) for r in observed}):
        if not shop:raise ValueError('TGC sale lacks original storefront identity')
        result['tgc',shop]={'shop_name_current':registered.get(shop,{}).get('shop_name_observed') or shop,
                          'opened_on':None,'is_active':1,'scope_basis':'original_tgc_storefront',
                          'registered_storefront':shop in registered,
                          'effective_start':registered.get(shop,{}).get('effective_start'),
                          'effective_end':registered.get(shop,{}).get('effective_end')}
    return result


def evidence(conn, shops, start, end):
    scopes=reporting_shops(conn,shops,start,end)
    snapshots=verified_snapshots(conn,end)
    contracts = query(conn, """SELECT contract_id,platform_code,source_code,query_time_semantics
        FROM control_data_source_contract WHERE UPPER(data_type)='ORDER'""")
    basis = {r['source_code']: text(r['query_time_semantics']) for r in contracts}
    audits = query(conn, """SELECT * FROM audit_data_coverage_day
        WHERE UPPER(data_type)='ORDER' AND business_date >= %s AND business_date < %s""", (start,end))
    proofs = {}
    for row in audits:
        shop=('tgc',text(row['platform_shop_id'])) if platform_code(row['platform_code'])=='tgc' else shops.resolve(row['platform_code'],row['platform_shop_id'],'')
        if not shop or row['source_code'] != NATIVE_SOURCE_CODES.get(shop[0]):
            continue
        key=(*shop,date_value(row['business_date']))
        previous=proofs.get(key)
        if previous is None or str(row['loaded_at'])>str(previous['loaded_at']):
            proofs[key]=row
    result=[]
    for shop,meta in sorted(scopes.items()):
        opened=date_value(meta['opened_on']) if meta['opened_on'] else None
        effective_start=date_value(meta['effective_start']) if meta.get('effective_start') else None
        effective_end=date_value(meta['effective_end']) if meta.get('effective_end') else None
        for day in days(start,end):
            # Unknown opening/closing dates cannot be turned into empty sales.
            if (opened and day<opened) or (effective_start and day<effective_start) or (effective_end and day>effective_end):
                continue
            proof=proofs.get((*shop,day))
            reason='collection_evidence_missing'
            status='missing'
            detail={'shop_name':meta['shop_name_current'],'opened_on':str(opened or ''),
                    'registry_active':meta['is_active'],'effective_start':str(effective_start or ''),
                    'effective_end':str(effective_end or '')}
            if meta.get('retired_registry_identity'):
                detail['retired_registry_identity']=meta['retired_registry_identity']
            if meta.get('scope_basis'):
                detail['scope_basis']=meta['scope_basis']
            if meta.get('scope_basis')=='original_tgc_storefront':
                detail['registered_storefront']=meta['registered_storefront']
                if not meta['registered_storefront']:
                    result.append((*shop,day,'missing','storefront_identity_unverified',detail))
                    continue
            snapshot=snapshots.get(shop)
            if snapshot and date_value(snapshot['coverage_start'])<=day<date_value(snapshot['coverage_end']):
                detail['native_snapshot']=snapshot
                if proof and str(proof['loaded_at'])>snapshot['observed_at'] and proof['completeness_status']!='READY':
                    detail['source_audit']={k:proof.get(k) for k in ('source_code','run_id','loaded_at','completeness_status')}
                    result.append((*shop,day,'missing','newer_source_read_failed',detail))
                    continue
                reason='official_paid_window_reconciled' if snapshot.get('source_kind')=='official_paid_export' else 'full_creation_history_reconciled'
                result.append((*shop,day,'verified',reason,detail))
                continue
            if proof:
                detail['source_audit']={k:proof.get(k) for k in ('source_code','run_id','business_date','row_count','business_key_count','zero_data_confirmed','completeness_status','coverage_notes','loaded_at')}
                semantics=basis.get(proof['source_code'],'')
                detail['query_time_semantics']=semantics
                if proof['completeness_status']!='READY':
                    reason='source_'+text(proof['completeness_status']).lower()
                elif not proof['row_count'] and not proof['zero_data_confirmed']:
                    reason='zero_not_verified'
                else:
                    # The contract must explicitly certify a payment window.
                    # Creation-time audit dates are retained as evidence but
                    # cannot certify this denominator without lifecycle closure.
                    if semantics == 'PAID_AT':
                        status='verified';reason='official_paid_window_reconciled'
                    else:
                        reason='payment_window_not_reconciled'
            result.append((*shop,day,status,reason,detail))
    return result


def require_unchanged_coverage(conn,batch,start,end,require_all_verified=True):
    """A verification made before a source failure cannot authorize cutover."""
    import json
    from crm_sales_sources import Shops
    stored=query(conn,'SELECT * FROM crm_report_coverage WHERE batch_id=%s',(batch,))
    expected=sorted((r['platform'],r['shop_key'],str(r['stat_date']),r['status'],r['reason'],
                     canonical(json.loads(r['evidence_json']))) for r in stored)
    current=sorted((platform,shop,str(day),status,reason,canonical(detail))
                   for platform,shop,day,status,reason,detail in evidence(conn,Shops(conn),start,end))
    if not expected or expected!=current or (require_all_verified and any(r[3]!='verified' for r in current)):
        raise ValueError('native source coverage changed or failed after candidate snapshot; rebuild before publication')
