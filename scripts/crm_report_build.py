#!/usr/bin/env python3
"""Build an isolated immutable candidate; never replace a published batch here.

Every source read uses one repeatable-read transaction. The write connection
stores a candidate and its evidence, never mutates native facts or live totals.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import re
import uuid
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta
from pathlib import Path

from crm_schema import connect_mysql
from crm_report_schema import ensure_report_schema
from crm_report_model import canonical,identity,legacy_current_facts,reconcile_source_facts,resolve_sale,text
from crm_report_coverage import evidence as coverage_evidence
from crm_report_scope import recent_release_scope
from crm_original_order_read import require_complete_read
from crm_pipeline_version import pipeline_fingerprint
from crm_report_integrity import record_sets
from crm_sales_sources import Shops,query,match_native_orders

CATEGORIES={'快递问题','库房问题','买家问题','产品问题','运营问题'}


def banniu_import_proof(conn,start,end):
    """Prove the release-scope API rows were imported without loss or mutation."""
    database=os.environ.get('CRM_BANNIU_SOURCE_DATABASE','ecom_profit')
    if not re.fullmatch(r'[A-Za-z0-9_]+',database):raise ValueError('invalid Banniu source database name')
    source=query(conn,f"""SELECT
        COALESCE(NULLIF(api_task_id,''),NULLIF(aftersales_id,''),CONCAT('legacy-',CAST(id AS CHAR))) ticket,
        COALESCE(NULLIF(api_child_key,''),CAST(id AS CHAR)) item,raw_payload,api_updated_at
        FROM `{database}`.ods_banniu_aftersales
        WHERE source_file_name='banniu_api' AND api_created_at>=%s AND api_created_at<%s
        ORDER BY ticket,item""",(start,end))
    imported=query(conn,"""SELECT source_ticket_id ticket,source_item_id item,raw_payload,api_updated_at
        FROM ods_crm_aftersales WHERE source_system='banniu' AND included_in_analytics=1
        AND api_created_at>=%s AND api_created_at<%s ORDER BY ticket,item""",(start,end))
    def signature(rows):
        digest=hashlib.sha256()
        keys=[]
        for row in rows:
            key=(text(row['ticket']),text(row['item']))
            keys.append(key)
            digest.update(canonical([*key,row['raw_payload'],row['api_updated_at']]).encode()+b'\n')
        if len(keys)!=len(set(keys)):raise ValueError('Banniu source scope contains duplicate item identities')
        return keys,digest.hexdigest()
    source_keys,source_digest=signature(source);imported_keys,imported_digest=signature(imported)
    if source_keys!=imported_keys or source_digest!=imported_digest:
        raise ValueError('Banniu API source and unified fact import differ in release scope')
    return {'rows':len(source),'tickets':len({ticket for ticket,_ in source_keys}),'sha256':source_digest,'sourceDatabase':database}


def rules_snapshot(conn):
    return [dict(p1=r['problem1'],p2=r['problem2'],p3=r['problem3_pattern'],note=r['note'],
                 enabled=bool(r['is_enabled']),updatedBy=r['updated_by'],updatedAt=str(r['updated_at']))
            for r in query(conn,'SELECT * FROM dim_crm_exclusion_rule ORDER BY problem1,problem2,problem3_pattern')]


def classification(fact,rules):
    p1=text(fact['problem1']);p2=text(fact['problem2']) or '未填写';p3=text(fact['problem3']) or '未填写'
    if p1 not in CATEGORIES:return {'status':'unclassified','rule':None}
    matched=next((r for r in rules if r['enabled'] and r['p1']==p1 and r['p2']==p2 and r['p3'] in ('*',p3)),None)
    return {'status':'excluded' if matched else 'operating','rule':matched}


def included(fact,rules):
    return classification(fact,rules)['status']=='operating'


def current_facts(conn,end,start=None):
    rows=query(conn,"SELECT * FROM ods_crm_aftersales WHERE api_created_at<%s",(end,))
    legacy,retired=legacy_current_facts([r for r in rows if r['source_system']=='banniu' and r['included_in_analytics']])
    source_rows=legacy+[r for r in rows if r['source_system']=='ticket_service' and r['included_in_analytics']]
    mappings=query(conn,'SELECT * FROM crm_issue_migration_map ORDER BY left_input_key,right_input_key')
    facts=reconcile_source_facts(source_rows,mappings)
    if start is not None:facts=[r for r in facts if r['api_created_at'].date()>=start]
    return facts,retired


def insert_many(conn,table,columns,rows):
    if not rows:return
    with conn.cursor() as cur:
        cur.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(['%s']*len(columns))})",rows)


def unapproved_denominator_rows(batch,scope):
    rows=[]
    periods={(period['start'],period['end']) for period in scope['requiredPeriods']}
    for period_start,period_end in sorted(periods):
        for grain in ('total','merchant_code','sales_link','warehouse','warehouse_sales_link'):
            rows.append((batch,period_start,period_end,grain,'',0,'sales_coverage_not_approved'))
    return rows


def build(source,writer,end,artifact_dir):
    artifact_dir=artifact_dir.resolve()
    pipeline_sha=pipeline_fingerprint()
    batch='report_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    scope=recent_release_scope(end);start=date.fromisoformat(scope['requiredStart'])
    retained_facts,retired=current_facts(source,end)
    earliest_created=min((f['api_created_at'] for f in retained_facts),default=None)
    facts=[f for f in retained_facts if f['api_created_at'].date()>=start]
    if not facts:raise ValueError('no source facts; refusing empty replacement')
    banniu_proof=banniu_import_proof(source,start,end)
    source_batches=query(source,"""SELECT * FROM etl_crm_ticket_batches WHERE source_system='ticket_service'
        AND status='published' AND reconciliation_status='approved'
        AND coverage_start<=%s AND coverage_end>=%s ORDER BY completed_at DESC LIMIT 1""",(start,end))
    if not source_batches:raise ValueError('complete post-cutover ticket history has not been collected')
    sb=source_batches[0]
    original_batch=require_complete_read(source,end,sb['batch_id'])
    manifest=query(source,'SELECT COUNT(*) n FROM crm_ticket_read_segment WHERE batch_id=%s',(sb['batch_id'],))
    if not manifest[0]['n']:raise ValueError('ticket source lacks stable segment and empty-page evidence')
    rules=rules_snapshot(source);shops=Shops(source)
    coverage=coverage_evidence(source,shops,start,end)
    blocks=Counter(r[4] for r in coverage if r[3]!='verified')
    day_status=defaultdict(list)
    for entry in coverage:day_status[entry[2]].append(entry[3]=='verified')
    through=start
    while through<end and day_status.get(through) and all(day_status[through]):through+=timedelta(days=1)
    complete_through=str(through-timedelta(days=1)) if through>start else ''
    artifact_dir.mkdir(parents=True,exist_ok=True)
    path=artifact_dir/(batch+'.jsonl.gz')
    source_inputs=sum(len(f['_source_inputs']) for f in facts)
    merged_duplicates=source_inputs-len(facts)
    source_counts=Counter(ref['source_system'] for f in facts for ref in f['_source_inputs'])
    summary={'rules':rules,'completeThrough':complete_through,'retired_fact_ids':retired,'coverageReasons':dict(blocks),'releaseScope':scope,'originalOrderBatchId':original_batch,'earliestCreatedAt':str(earliest_created),'pipelineSha256':pipeline_sha,
             'issueCoverageApproved':True,'salesCoverageApproved':False,
             'banniuImportProof':banniu_proof,
             'sourceInputConservation':{'sourceInputs':source_inputs,'canonicalIssues':len(facts),'mergedDuplicates':merged_duplicates,'bySource':dict(source_counts)}}
    insert_many(writer,'crm_report_batch', ['batch_id','status','started_at','coverage_start','coverage_end','source_batch_id','source_synced_at','issue_count','summary_json','evidence_path'],
                [(batch,'building',datetime.now(),start,end,sb['batch_id'],sb['completed_at'],len(facts),canonical(summary),str(path))])
    writer.commit()
    try:
        matched_orders=match_native_orders(source,shops,facts,
            progress=lambda p,s,n: print(canonical({'platform':p,'shop':s,'requested_orders':n}),flush=True))
        with gzip.open(path,'wt',encoding='utf-8') as out:
            out.write(canonical({'batch':batch,'rules':rules,'retired_fact_ids':retired,'pipelineSha256':pipeline_sha,'releaseScope':scope})+'\n')
            result=[];reasons=Counter();changed=[]
            for fact in facts:
                shop=fact['_shop']
                sales=list(matched_orders.get((*shop,text(fact['order_no'])),{}).values()) if shop else []
                complete=bool(sales) and all(s.get('original_order_complete') for s in sales)
                match=resolve_sale(fact,sales,order_complete=complete) if shop else {'status':'missing','reason':'original_sales_line_missing','code':'','sales':[]}
                reasons[match['reason']]+=1
                # Keep raw merchant codes separate from the derived native spec.
                native=match['sales'];products={s['product_id'] for s in native};links={s['link_key'] for s in native}
                product=next(iter(products)) if match['status']=='verified' and len(products)==1 else ''
                link=next(iter(links)) if match['status']=='verified' and len(links)==1 else ''
                native_shops={(s['platform'],s['shop_key']) for s in native}
                report_shop=next(iter(native_shops)) if match['status']=='verified' and len(native_shops)==1 else shop
                classed=classification(fact,rules)
                proof={'rawWarehouseCode':fact.get('source_warehouse_code'),'warehouseConflict':fact.get('warehouse_match_status')=='conflict','sourceShopKey':shop,'shop_resolution':fact.get('_shop_evidence','source_shop_registry'),'source_hash':identity(fact['raw_payload']),'sales':[s['evidence'] for s in native],
                       'candidateSalesLines':[{'lineKey':s['line_key'],'code':s.get('code',''),'productId':s.get('product_id',''),'nativeSkuId':s.get('native_sku_id',''),'subKeys':sorted(s.get('sub_keys',[]))} for s in sales],
                       'evidenceHits':match.get('evidence_hits',[]),
                       'sourceRefs':fact['_source_inputs'],'reconciliationReason':fact['_reconciliation_reason'],
                       'classificationStatus':classed['status'],'exclusionRule':classed['rule']}
                row=(batch,fact['_canonical_issue_key'],fact['id'],fact['source_system'],str(fact['source_ticket_id']),str(fact['source_item_id']),fact['api_created_at'],report_shop[0] if report_shop else '',report_shop[1] if report_shop else '',text(fact['merchant_code']),match['code'],product,text(fact['product_title']),link,text(fact['problem1']),text(fact['problem2']),text(fact['problem3']),'' if fact.get('warehouse_match_status')=='conflict' else text(fact['source_warehouse_code']),'' if fact.get('warehouse_match_status')=='conflict' else text(fact['source_warehouse_name']),int(classed['status']=='operating'),match['status'],match['reason'],canonical(proof))
                result.append(row)
                out.write(canonical({'issue':row[1],'fact':fact['id'],'old_code':fact['merchant_code'],'code':match['code'],'reason':match['reason'],'proof':proof})+'\n')
                if text(fact['merchant_code'])!=match['code']:changed.append({'fact':fact['id'],'old_code':fact['merchant_code'],'code':match['code'],'reason':match['reason']})
            insert_many(writer,'crm_report_issue',['batch_id','issue_key','source_fact_id','source_system','source_ticket_id','source_item_id','created_at','platform','shop_key','raw_code','merchant_code','product_id','product_title','denominator_key','problem1','problem2','problem3','warehouse_code','warehouse_name','included_operating','match_status','match_reason','evidence_json'],result)
            lineage=[]
            for fact in facts:
                for ref in fact['_source_inputs']:
                    lineage.append((batch,ref['input_key'],fact['_canonical_issue_key'],ref['source_fact_id'],ref['source_system'],ref['source_ticket_id'],ref['source_item_id'],
                                    'retained' if len(fact['_source_inputs'])==1 else 'merged_duplicate',fact['_reconciliation_reason'],
                                    canonical({'canonicalIssueKey':fact['_canonical_issue_key'],'sourceCount':len(fact['_source_inputs'])})))
            insert_many(writer,'crm_report_issue_source',['batch_id','input_key','canonical_issue_key','source_fact_id','source_system','source_ticket_id','source_item_id','decision','decision_reason','evidence_json'],lineage)
            incomplete=unapproved_denominator_rows(batch,scope)
            insert_many(writer,'crm_report_denominator_status',['batch_id','period_start','period_end','grain_type','grain_key','is_complete','reason'],incomplete)
            writer.commit()
        summary['warehouseEvidence']={'state':'source_issue_evidence_only','salesCoverageApproved':False}
        os.chmod(path,0o600)
        insert_many(writer,'crm_report_coverage',['batch_id','platform','shop_key','stat_date','status','reason','evidence_json'],[(batch,*r[:5],canonical(r[5])) for r in coverage])
        summary.update(matchReasons=dict(reasons),changed=changed,quantityConservation={'operating':sum(r[19] for r in result),'matchedOperating':sum(r[19] for r in result if r[10]),'unmatchedOperating':sum(r[19] for r in result if not r[10])})
        summary['recordSets'] = record_sets(writer, batch)
        if pipeline_fingerprint()!=pipeline_sha:raise ValueError('report calculation code changed during the build')
        with writer.cursor() as cur:
            cur.execute("UPDATE crm_report_batch SET status='candidate',completed_at=%s,summary_json=%s WHERE batch_id=%s",(datetime.now(),canonical(summary),batch))
        writer.commit()
        print(canonical({'batch':batch,'status':'candidate','coverageReasons':dict(blocks),'matchReasons':dict(reasons)}),flush=True)
    except Exception as exc:
        writer.rollback()
        with writer.cursor() as cur:cur.execute("UPDATE crm_report_batch SET status='failed',error_summary=%s,completed_at=%s WHERE batch_id=%s",(str(exc)[:1000],datetime.now(),batch))
        writer.commit();raise
    return batch


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--end',type=date.fromisoformat,required=True);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--result-file',type=Path)
    args=p.parse_args();source=connect_mysql();writer=connect_mysql()
    try:
        ensure_report_schema(writer)
        with source.cursor() as cur:
            cur.execute('SET SESSION MAX_EXECUTION_TIME=30000')
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        batch=build(source,writer,args.end,args.artifacts)
        if args.result_file:
            args.result_file.write_text(canonical({'batch_id':batch}),encoding='utf-8')
    finally:
        source.rollback();source.close();writer.close()
