#!/usr/bin/env python3
"""Rebuild product denominators from current native sales lines.

This never reads ``crm_report_orders`` from another report batch.  Every
value/zero/unknown decision is tied to a newly generated sales-fact artifact
and the candidate's platform/shop/day coverage matrix.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import uuid
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta
from pathlib import Path

from crm_schema import connect_mysql
from crm_report_integrity import record_sets
from crm_report_model import SalesAggregation,canonical
from crm_sales_sources import Shops,query,read_sales


def day_range(start,end):
    while start<end:
        yield start;start+=timedelta(days=1)


def main(batch,artifact_dir):
    conn=connect_mysql()
    try:
        with conn.cursor() as cur:
            cur.execute('SET SESSION MAX_EXECUTION_TIME=30000')
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
        rows=query(conn,'SELECT * FROM crm_report_batch WHERE batch_id=%s FOR UPDATE',(batch,))
        if len(rows)!=1 or rows[0]['status']!='candidate':raise ValueError('product denominators require an isolated candidate')
        report=rows[0];summary=json.loads(report['summary_json']);scope=summary['releaseScope']
        start=date.fromisoformat(scope['requiredStart']);end=date.fromisoformat(scope['requiredEnd'])
        periods=sorted({(date.fromisoformat(p['start']),date.fromisoformat(p['end'])) for p in scope['requiredPeriods']})
        sales_batch='sales_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
        artifact_dir.mkdir(parents=True,exist_ok=True);artifact=artifact_dir/(sales_batch+'.jsonl.gz')
        shops=Shops(conn);aggregation=SalesAggregation();fact_digest=hashlib.sha256();fact_count=0
        code_shops=defaultdict(set);period_blocks=defaultdict(set)
        with gzip.open(artifact,'wt',encoding='utf-8') as stream:
            for sale in read_sales(conn,shops,start,end):
                aggregation.add(sale);fact_count+=1
                if sale['code']:code_shops[sale['code']].add((sale['platform'],sale['shop_key']))
                paid=sale['paid_at'].date();containing=[p for p in periods if p[0]<=paid<p[1]]
                if (not sale['code'] or not sale.get('sales_identity_known',True)) and (sale['shipped'] or not sale.get('shipping_known',False)):
                    for period in containing:period_blocks[period].add('sales_spec_identity_missing')
                elif sale['code'] and not sale['shipped'] and not sale.get('shipping_known',False):
                    for period in containing:period_blocks[period].add('shipping_evidence_incomplete:'+sale['code'])
                item={'salesBatchId':sales_batch,'lineKey':sale['line_key'],'orderKey':sale['order_key'],
                    'platform':sale['platform'],'shopKey':sale['shop_key'],'merchantCode':sale['code'],
                    'quantity':str(sale['quantity']),'paidAt':str(sale['paid_at']),'shipped':sale['shipped'],
                    'shippingKnown':sale.get('shipping_known',False),'salesIdentityKnown':sale.get('sales_identity_known',True),
                    'evidence':sale['evidence']}
                encoded=(canonical(item)+'\n').encode();fact_digest.update(encoded);stream.write(encoded.decode())
        issues=query(conn,"""SELECT DISTINCT merchant_code,platform,shop_key FROM crm_report_issue
            WHERE batch_id=%s AND included_operating=1 AND merchant_code<>''""",(batch,))
        codes=sorted({row['merchant_code'] for row in issues})
        for row in issues:
            if row['platform'] and row['shop_key']:code_shops[row['merchant_code']].add((row['platform'],row['shop_key']))
        coverage={(row['platform'],row['shop_key'],str(row['stat_date'])):row for row in query(conn,
            'SELECT * FROM crm_report_coverage WHERE batch_id=%s',(batch,))}
        stats={(a,b,g,k):(orders,qty) for a,b,g,k,orders,qty in aggregation.periods(start,end) if g=='merchant_code'}
        frozen={(str(row['period_start']),str(row['period_end']),row['merchant_code']):row for row in query(conn,
            'SELECT * FROM crm_report_product_metric WHERE batch_id=%s',(batch,))}
        metrics=[];decisions=[];states=Counter()
        for period_start,period_end in periods:
            for code in codes:
                related=sorted(code_shops[code]);reasons=set(period_blocks[period_start,period_end])
                if not related:reasons.add('product_shop_scope_not_proven')
                missing=[]
                for platform,shop in related:
                    for day in day_range(period_start,period_end):
                        proof=coverage.get((platform,shop,str(day)))
                        if not proof or proof['status']!='verified':
                            missing.append({'platform':platform,'shop':shop,'day':str(day),'reason':proof['reason'] if proof else 'coverage_row_missing'})
                code_shipping='shipping_evidence_incomplete:'+code
                if code_shipping in reasons:
                    reasons.remove(code_shipping);reasons.add('shipping_evidence_incomplete')
                # A missing-code sale can belong to any product, so it blocks
                # every product in that period. Other code-specific shipping
                # gaps do not contaminate this product.
                reasons={r for r in reasons if not r.startswith('shipping_evidence_incomplete:')}
                if missing:reasons.add('platform_shop_period_incomplete')
                value=stats.get((period_start,period_end,'merchant_code',code))
                previous=frozen.get((str(period_start),str(period_end),code))
                if reasons and previous and previous['sales_status']=='frozen_verified':
                    state='frozen_verified';reason='fresh_unavailable_using_frozen';order_count=None;sales_qty=previous['sales_qty']
                    order_status='unavailable';sales_status='frozen_verified';source_batch=previous['source_batch'];source_artifact=previous['source_artifact'];evidence_hash=previous['evidence_hash']
                elif reasons:
                    state='unavailable';reason='+'.join(sorted(reasons));order_count=None;sales_qty=None
                    order_status='unavailable';sales_status='unavailable';source_batch=sales_batch;source_artifact=str(artifact)
                    evidence_hash=hashlib.sha256(canonical([sales_batch,str(period_start),str(period_end),code,reason]).encode()).hexdigest()
                elif value:
                    state='fresh_verified';reason='current_native_sales_lines_verified';order_count=value[0];sales_qty=value[1]
                    order_status='fresh_verified';sales_status='fresh_verified';source_batch=sales_batch;source_artifact=str(artifact)
                    evidence_hash=hashlib.sha256(canonical([sales_batch,str(period_start),str(period_end),code,str(value[0]),str(value[1])]).encode()).hexdigest()
                else:
                    state='fresh_verified';reason='all_related_platform_shop_days_verified_empty';order_count=0;sales_qty=0
                    order_status='fresh_verified';sales_status='fresh_verified';source_batch=sales_batch;source_artifact=str(artifact)
                    evidence_hash=hashlib.sha256(canonical([sales_batch,str(period_start),str(period_end),code,'verified_zero']).encode()).hexdigest()
                states[state]+=1
                metrics.append((batch,period_start,period_end,code,order_count,sales_qty,order_status,sales_status,reason,source_batch,source_artifact,evidence_hash))
                decisions.append({'salesBatchId':sales_batch,'merchantCode':code,'periodStart':str(period_start),'periodEnd':str(period_end),
                    'state':state,'orderCount':order_count,'salesQty':str(sales_qty) if sales_qty is not None else None,
                    'relatedShops':[{'platform':p,'shopKey':s} for p,s in related],'missingCoverage':missing,'reason':reason})
        decision_path=artifact_dir/(sales_batch+'-product-decisions.jsonl.gz');decision_digest=hashlib.sha256()
        with gzip.open(decision_path,'wt',encoding='utf-8') as stream:
            for item in decisions:
                encoded=(canonical(item)+'\n').encode();decision_digest.update(encoded);stream.write(encoded.decode())
        with conn.cursor() as cur:
            cur.execute('DELETE FROM crm_report_product_metric WHERE batch_id=%s',(batch,))
            cur.executemany("""INSERT INTO crm_report_product_metric
                (batch_id,period_start,period_end,merchant_code,order_count,sales_qty,order_status,sales_status,reason,source_batch,source_artifact,evidence_hash)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",metrics)
        summary.update(productMetricLayer=True,productSalesCoverageApproved=False,
            salesFactBatchId=sales_batch,salesFactRows=fact_count,salesFactSha256=fact_digest.hexdigest(),salesFactArtifact=str(artifact),
            productDecisionRows=len(decisions),productDecisionSha256=decision_digest.hexdigest(),productDecisionArtifact=str(decision_path),
            productDenominatorStates=dict(states))
        summary['recordSets']=record_sets(conn,batch)
        with conn.cursor() as cur:cur.execute('UPDATE crm_report_batch SET summary_json=%s WHERE batch_id=%s',(canonical(summary),batch))
        conn.commit();print(canonical({'batch':batch,'salesFactBatchId':sales_batch,'salesFactRows':fact_count,'states':dict(states)}))
    except Exception:
        conn.rollback();raise
    finally:conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--batch',required=True);parser.add_argument('--artifacts',type=Path,required=True)
    args=parser.parse_args();main(args.batch,args.artifacts)
