#!/usr/bin/env python3
"""Validate and atomically select an immutable report; failed candidates stay isolated."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime,time
from pathlib import Path
from crm_schema import connect_mysql
from crm_sales_sources import query
from crm_report_build import banniu_import_proof,rules_snapshot,current_facts,included
from crm_report_model import canonical,identity,text
from crm_report_scope import validate_release_scope
from crm_original_order_read import require_complete_read
from crm_pipeline_version import pipeline_fingerprint
from crm_report_coverage import require_unchanged_coverage
from crm_report_integrity import require_record_sets

FULL='full'
PARTIAL='issues_full_denominators_partial'


def coverage_policy(row,expected_days,verification_kind):
    if verification_kind not in (FULL,PARTIAL):raise ValueError('unsupported publication verification kind')
    if not row['n'] or row['days']!=expected_days:
        raise ValueError('shop/date coverage matrix is incomplete')
    gaps=int(row['gaps'] or 0)
    if verification_kind==FULL and gaps:
        raise ValueError('shop/date/paid-window coverage remains incomplete; no publication')
    return gaps


def snapshot_policy(summary,verification_kind):
    if not isinstance(summary.get('rules'),list) or (verification_kind==FULL and not summary.get('completeThrough')):
        raise ValueError('continuous coverage or classification snapshot missing')


def verify_attribution_evidence(rows):
    """Every verified product attribution must retain real platform line proof."""
    for row in rows:
        if row['match_status']!='verified':
            continue
        evidence=json.loads(row['evidence_json'])
        sales=evidence.get('sales') or []
        if not row['platform'] or not row['shop_key'] or not row['merchant_code'] or not sales:
            raise ValueError('verified issue lacks a real platform sales line')
        if any(item.get('issue_mapping_only') or not item.get('table') or not item.get('row_key') for item in sales):
            raise ValueError('verified issue uses candidate-only evidence instead of an original sales line')


def verify_product_denominators(conn,batch,summary,scope):
    if summary.get('productMetricLayer'):
        codes={row['merchant_code'] for row in query(conn,"""SELECT DISTINCT merchant_code FROM crm_report_issue
            WHERE batch_id=%s AND included_operating=1 AND merchant_code<>''""",(batch,))}
        expected={(p['start'],p['end'],code) for p in scope['requiredPeriods'] for code in codes}
        metrics=query(conn,'SELECT * FROM crm_report_product_metric WHERE batch_id=%s',(batch,))
        actual={(str(row['period_start']),str(row['period_end']),row['merchant_code']) for row in metrics}
        if actual!=expected or len(actual)!=len(metrics):raise ValueError('product metric states are incomplete or duplicated')
        allowed={'frozen_verified','fresh_verified','unavailable','conflict'}
        for row in metrics:
            if row['sales_status'] not in allowed or row['order_status'] not in allowed:
                raise ValueError('unsupported product metric state')
            if not row['source_batch'] or not row['source_artifact'] or not row['evidence_hash']:
                raise ValueError('displayed product metric lacks source evidence')
            if row['sales_status']=='frozen_verified' and (row['sales_qty'] is None or row['sales_qty']<=0):
                raise ValueError('frozen metric is not a proven positive sale')
            if row['sales_status'] in ('unavailable','conflict') and row['sales_qty'] is not None:
                raise ValueError('unknown/conflicting sales metric contains a value')
            if row['order_status'] in ('unavailable','conflict') and row['order_count'] is not None:
                raise ValueError('unknown/conflicting order metric contains a value')
            if row['sales_status']=='fresh_verified' and row['sales_qty'] is None:
                raise ValueError('fresh verified sales metric lacks a value')
            if row['order_status']=='fresh_verified' and row['order_count'] is None:
                raise ValueError('fresh verified order metric lacks a value')
        artifacts={row['source_artifact'] for row in metrics if row['sales_status'] in ('frozen_verified','fresh_verified') or row['order_status']=='fresh_verified'}
        if any(not Path(path).is_file() for path in artifacts):raise ValueError('product metric source artifact missing')
        frozen=summary.get('frozenSourceArtifact')
        if frozen:
            digest=hashlib.sha256()
            with gzip.open(frozen,'rb') as stream:
                for line in stream:digest.update(line)
            if digest.hexdigest()!=summary.get('frozenSourceSha256'):raise ValueError('frozen sales artifact changed')
        return
    if not summary.get('productSalesCoverageApproved'):
        return
    sales_batch=summary.get('salesFactBatchId','')
    if not sales_batch.startswith('sales_') or summary.get('productSalesSourceBatchId'):
        raise ValueError('product denominator does not use a newly generated native sales batch')
    for key in ('salesFactArtifact','productDecisionArtifact'):
        path=Path(summary.get(key,''))
        if not path.is_file():raise ValueError('product denominator evidence artifact missing')
    digest=hashlib.sha256()
    with gzip.open(summary['salesFactArtifact'],'rb') as stream:
        for line in stream:digest.update(line)
    if digest.hexdigest()!=summary.get('salesFactSha256'):
        raise ValueError('native sales fact artifact changed')
    digest=hashlib.sha256()
    with gzip.open(summary['productDecisionArtifact'],'rb') as stream:
        for line in stream:digest.update(line)
    if digest.hexdigest()!=summary.get('productDecisionSha256'):
        raise ValueError('product denominator decision artifact changed')
    codes={row['merchant_code'] for row in query(conn,"""SELECT DISTINCT merchant_code FROM crm_report_issue
        WHERE batch_id=%s AND included_operating=1 AND merchant_code<>''""",(batch,))}
    expected={(p['start'],p['end'],code) for p in scope['requiredPeriods'] for code in codes}
    states=query(conn,"""SELECT period_start,period_end,grain_key,is_complete,reason FROM crm_report_denominator_status
        WHERE batch_id=%s AND grain_type='merchant_code' AND grain_key<>''""",(batch,))
    actual={(str(row['period_start']),str(row['period_end']),row['grain_key']) for row in states}
    if actual!=expected or len(actual)!=len(states):raise ValueError('product-week denominator states are incomplete or duplicated')
    values={(str(row['period_start']),str(row['period_end']),row['grain_key']) for row in query(conn,"""SELECT period_start,period_end,grain_key
        FROM crm_report_orders WHERE batch_id=%s AND grain_type='merchant_code'""",(batch,))}
    for row in states:
        key=(str(row['period_start']),str(row['period_end']),row['grain_key'])
        if row['is_complete'] and key not in values and row['reason']!='all_related_platform_shop_days_verified_empty':
            raise ValueError('product zero lacks complete platform/shop/period evidence')
        if not row['is_complete'] and key in values:
            raise ValueError('uncovered product denominator published a numeric value')


def verify_current_issue_set(conn,data_batch,start,end,rules):
    """Compare report membership with current authoritative item sets.

    This catches omitted or residual children even if the report's own totals
    happen to balance. Classification uses this report's rules, including a
    rule-only batch that reuses previously verified source facts.
    """
    facts,_=current_facts(conn,end,start)
    expected={f['_canonical_issue_key']:f for f in facts}
    if len(expected)!=len(facts):raise ValueError('current source item identities are not unique')
    actual=query(conn,'SELECT * FROM crm_report_issue WHERE batch_id=%s',(data_batch,))
    if {r['issue_key'] for r in actual}!=set(expected) or len(actual)!=len(expected):
        raise ValueError('report item set differs from current authoritative source items')
    totals=dict(operating=0,matchedOperating=0,unmatchedOperating=0)
    for row in actual:
        fact=expected[row['issue_key']]
        if (row['created_at']!=fact['api_created_at'] or row['source_fact_id']!=fact['id']
            or any(text(row[field])!=text(fact[field]) for field in ('problem1','problem2','problem3'))
            or text(row['raw_code'])!=text(fact['merchant_code'])):
            raise ValueError('report item source fields changed after snapshot')
        if included(fact,rules):
            totals['operating']+=1
            totals['matchedOperating' if row['merchant_code'] else 'unmatchedOperating']+=1
    expected_sources={ref['input_key']:(key,ref) for key,fact in expected.items() for ref in fact['_source_inputs']}
    stored=query(conn,'SELECT * FROM crm_report_issue_source WHERE batch_id=%s',(data_batch,))
    if len(stored)!=len(expected_sources) or {r['input_key'] for r in stored}!=set(expected_sources):
        raise ValueError('report source reconciliation does not conserve every source item')
    for row in stored:
        canonical_key,ref=expected_sources[row['input_key']]
        if (row['canonical_issue_key']!=canonical_key or row['source_system']!=ref['source_system']
            or row['source_ticket_id']!=ref['source_ticket_id'] or row['source_item_id']!=ref['source_item_id']):
            raise ValueError('report source reconciliation changed after snapshot')
    return totals,dict(sourceInputs=len(expected_sources),canonicalIssues=len(expected),mergedDuplicates=len(expected_sources)-len(expected),
                       bySource=dict(Counter(ref['source_system'] for _,ref in expected_sources.values())))


def validate(conn,batch,verification_kind=FULL):
    rows=query(conn,'SELECT * FROM crm_report_batch WHERE batch_id=%s FOR UPDATE',(batch,))
    if len(rows)!=1 or rows[0]['status'] not in ('candidate','verified'):
        raise ValueError('batch is not a completed candidate')
    row=rows[0];summary=json.loads(row['summary_json'])
    if summary.get('pipelineSha256')!=pipeline_fingerprint():
        raise ValueError('report calculation code differs from this candidate build')
    scope=validate_release_scope(summary.get('releaseScope'),row['coverage_start'],row['coverage_end'])
    data_batch=summary.get('dataBatchId',batch)
    require_record_sets(conn,data_batch,summary.get('recordSets'))
    if canonical(summary.get('rules')) != canonical(rules_snapshot(conn)):
        raise ValueError('classification rules changed while candidate was built; rebuild before publication')
    if summary.get('banniuImportProof')!=banniu_import_proof(conn,row['coverage_start'],row['coverage_end']):
        raise ValueError('Banniu source or unified import changed after candidate build')
    latest=query(conn,"SELECT batch_id,status,reconciliation_status FROM etl_crm_ticket_batches WHERE source_system='ticket_service' ORDER BY started_at DESC,batch_id DESC LIMIT 1")
    if not latest or latest[0]['status']!='published' or latest[0]['reconciliation_status']!='approved' or latest[0]['batch_id']!=row['source_batch_id']:
        raise ValueError('ticket source changed or failed after candidate source snapshot')
    if not summary.get('originalOrderBatchId'):raise ValueError('original-order read batch missing')
    require_complete_read(conn,row['coverage_end'],row['source_batch_id'],summary['originalOrderBatchId'])
    path=Path(row['evidence_path'])
    if not path.is_file():raise ValueError('record-level evidence artifact missing')
    counts=query(conn,"""SELECT COUNT(*) n,SUM(included_operating) operating,
        SUM(included_operating=1 AND merchant_code<>'') matched,
        SUM(included_operating=1 AND merchant_code='') unmatched,
        SUM(match_status='verified' AND (merchant_code='' OR evidence_json='')) invalid
        FROM crm_report_issue WHERE batch_id=%s""",(data_batch,))[0]
    if counts['n']!=row['issue_count'] or counts['invalid']:
        raise ValueError('source issue count or attribution evidence inconsistent')
    if counts['operating']!=counts['matched']+counts['unmatched']:
        raise ValueError('operating quantity conservation failed')
    verify_attribution_evidence(query(conn,"""SELECT platform,shop_key,merchant_code,match_status,evidence_json
        FROM crm_report_issue WHERE batch_id=%s""",(data_batch,)))
    verify_product_denominators(conn,data_batch,summary,scope)
    actual_counts,source_conservation=verify_current_issue_set(conn,data_batch,row['coverage_start'],row['coverage_end'],summary['rules'])
    if actual_counts!=summary.get('quantityConservation'):
        raise ValueError('report classification totals differ from current source items and report rules')
    if not summary.get('issueCoverageApproved') or summary.get('salesCoverageApproved') is not False:
        raise ValueError('issue and sales coverage states are not explicit')
    if source_conservation!=summary.get('sourceInputConservation'):
        raise ValueError('source input conservation differs from the report snapshot')
    coverage=query(conn,"""SELECT COUNT(*) n,SUM(status<>'verified') gaps,
        COUNT(DISTINCT stat_date) days FROM crm_report_coverage WHERE batch_id=%s""",(data_batch,))[0]
    gaps=coverage_policy(coverage,(row['coverage_end']-row['coverage_start']).days,verification_kind)
    require_unchanged_coverage(conn,data_batch,row['coverage_start'],row['coverage_end'],verification_kind==FULL)
    snapshot_policy(summary,verification_kind)
    periods=query(conn,"""SELECT period_start,period_end,COUNT(DISTINCT grain_type) grains
        FROM crm_report_denominator_status WHERE batch_id=%s AND grain_key=''
        GROUP BY period_start,period_end""",(data_batch,))
    present={(str(r['period_start']),str(r['period_end'])) for r in periods if r['grains']==5}
    if any((p['start'],p['end']) not in present for p in scope['requiredPeriods']):
        raise ValueError('required complete/progress/comparison period not calculated')
    segments=query(conn,'SELECT * FROM crm_ticket_read_segment WHERE batch_id=%s ORDER BY segment_start',(row['source_batch_id'],))
    endpoint=datetime.combine(row['coverage_start'],time.min)
    for segment in segments:
        if segment['segment_start']!=endpoint or segment['pages_read']<2 or not segment['content_digest']:
            raise ValueError('source creation-history continuity not proven')
        endpoint=segment['segment_end']
    if endpoint.date()<row['coverage_end']:raise ValueError('ticket verification does not reach batch endpoint')
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest(),gaps


def select_batch(conn,batch,expected_current):
    current=query(conn,'SELECT batch_id FROM crm_report_current WHERE singleton=1 FOR UPDATE')
    actual=current[0]['batch_id'] if current else ''
    if actual!=expected_current:raise ValueError('current report changed; refusing stale publication')
    verified=query(conn,"SELECT status,summary_json FROM crm_report_batch WHERE batch_id=%s FOR UPDATE",(batch,))
    if not verified or verified[0]['status']!='verified':raise ValueError('report is not verified')
    # A successful earlier verification cannot authorize a stale candidate after
    # a rule edit, source failure, or modified evidence file. Holding the current
    # pointer lock serializes this check with the settings transaction.
    summary=json.loads(verified[0]['summary_json']);expected_digest=summary.get('evidenceSha256')
    verification_kind=summary.get('verificationKind',FULL)
    actual_digest,_=validate(conn,batch,verification_kind)
    if not expected_digest or actual_digest!=expected_digest:
        raise ValueError('verified evidence changed before publication')
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO crm_report_current(singleton,batch_id,published_at) VALUES(1,%s,NOW())
            ON DUPLICATE KEY UPDATE batch_id=VALUES(batch_id),published_at=VALUES(published_at)""",(batch,))
    return actual


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['verify','select']);p.add_argument('--batch',required=True)
    p.add_argument('--expected-current',default=None)
    p.add_argument('--verification-kind',choices=[FULL,PARTIAL],default=FULL)
    args=p.parse_args();conn=connect_mysql()
    try:
        if args.action=='verify':
            digest,gaps=validate(conn,args.batch,args.verification_kind)
            with conn.cursor() as cur:cur.execute("""UPDATE crm_report_batch SET status='verified',summary_json=JSON_SET(
                summary_json,'$.evidenceSha256',%s,'$.verificationKind',%s,'$.sourceCoverageApproved',%s,
                '$.sourceCoverageGapRows',%s) WHERE batch_id=%s""",
                (digest,args.verification_kind,args.verification_kind==FULL,gaps,args.batch))
        else:
            if args.expected_current is None:raise ValueError('--expected-current is required, empty string for first publication')
            previous=select_batch(conn,args.batch,args.expected_current)
        conn.commit()
        print(json.dumps({'action':args.action,'batch':args.batch,'previous':args.expected_current},ensure_ascii=False))
    except Exception:
        conn.rollback();raise
    finally:conn.close()
