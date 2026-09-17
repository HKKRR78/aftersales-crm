#!/usr/bin/env python3
"""Attach positive sales from the former production dashboard snapshot.

The legacy snapshot can prove a displayed positive sales quantity. It cannot
prove a zero or complete order coverage, so order_count remains NULL and no
missing product/week is converted to zero.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import date,datetime,timedelta
from pathlib import Path

from crm_schema import connect_mysql
from crm_report_integrity import record_sets
from crm_report_model import canonical
from crm_report_schema import ensure_report_schema
from crm_sales_sources import query


SOURCE_DATABASE='ecom_profit'
SOURCE_TABLE='dws_crm_order_weekly'


def main(batch,frozen_through,artifact_dir):
    conn=connect_mysql()
    try:
        ensure_report_schema(conn)
        report=query(conn,'SELECT * FROM crm_report_batch WHERE batch_id=%s FOR UPDATE',(batch,))
        if len(report)!=1 or report[0]['status']!='candidate':raise ValueError('frozen sales require an isolated candidate')
        summary=json.loads(report[0]['summary_json']);periods=sorted({(p['start'],p['end']) for p in summary['releaseScope']['requiredPeriods']})
        freeze_end=frozen_through+timedelta(days=1)
        codes=sorted({row['merchant_code'] for row in query(conn,"""SELECT DISTINCT merchant_code FROM crm_report_issue
            WHERE batch_id=%s AND included_operating=1 AND merchant_code<>''""",(batch,))})
        source_rows=query(conn,f"""SELECT week_start,week_end,grain_key,sales_qty,order_count,refreshed_at
            FROM `{SOURCE_DATABASE}`.`{SOURCE_TABLE}` WHERE grain_type='merchant_code'
              AND week_end<=%s AND sales_qty>0 AND grain_key IN ({','.join(['%s']*len(codes))})
            ORDER BY week_start,week_end,grain_key""",(freeze_end,*codes)) if codes else []
        source={(str(row['week_start']),str(row['week_end']),row['grain_key']):row for row in source_rows}
        refreshed=max((row['refreshed_at'] for row in source_rows),default=None)
        source_batch='legacy-production-dws-'+(refreshed.strftime('%Y%m%dT%H%M%S') if refreshed else 'empty')
        artifact_dir.mkdir(parents=True,exist_ok=True);artifact=artifact_dir/(source_batch+'.jsonl.gz')
        digest=hashlib.sha256();row_hashes={}
        with gzip.open(artifact,'wt',encoding='utf-8') as stream:
            for row in source_rows:
                item={'sourceDatabase':SOURCE_DATABASE,'sourceTable':SOURCE_TABLE,'weekStart':str(row['week_start']),
                    'weekEnd':str(row['week_end']),'merchantCode':row['grain_key'],'salesQty':str(row['sales_qty']),
                    'legacyOrderCount':row['order_count'],'refreshedAt':str(row['refreshed_at']),
                    'orderCountAccepted':False,'reason':'former_production_dashboard_positive_sales_snapshot'}
                encoded=(canonical(item)+'\n').encode();digest.update(encoded);stream.write(encoded.decode())
                row_hashes[(item['weekStart'],item['weekEnd'],item['merchantCode'])]=hashlib.sha256(encoded).hexdigest()
        records=[];counts={'frozen_verified':0,'unavailable':0}
        for start,end in periods:
            for code in codes:
                old=source.get((start,end,code)) if date.fromisoformat(end)<=freeze_end else None
                if old:
                    sales=old['sales_qty'];sales_status='frozen_verified';reason='former_production_positive_sales';counts['frozen_verified']+=1
                    evidence=row_hashes[start,end,code]
                else:
                    sales=None;sales_status='unavailable';reason='no_proven_positive_frozen_sales';counts['unavailable']+=1
                    evidence=hashlib.sha256(canonical([batch,start,end,code,reason]).encode()).hexdigest()
                records.append((batch,start,end,code,None,sales,'unavailable',sales_status,reason,source_batch,str(artifact),evidence))
        with conn.cursor() as cur:
            cur.execute('DELETE FROM crm_report_product_metric WHERE batch_id=%s',(batch,))
            cur.executemany("""INSERT INTO crm_report_product_metric
                (batch_id,period_start,period_end,merchant_code,order_count,sales_qty,order_status,sales_status,reason,source_batch,source_artifact,evidence_hash)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",records)
        summary.update(productMetricLayer=True,productSalesCoverageApproved=False,productOrderThrough=str(frozen_through),
            frozenThrough=str(frozen_through),frozenSourceBatch=source_batch,frozenSourceArtifact=str(artifact),
            frozenSourceRows=len(source_rows),frozenSourceSha256=digest.hexdigest(),frozenMetricStates=counts,
            frozenOrderCountsApproved=False)
        summary['recordSets']=record_sets(conn,batch)
        with conn.cursor() as cur:cur.execute('UPDATE crm_report_batch SET summary_json=%s WHERE batch_id=%s',(canonical(summary),batch))
        conn.commit();print(canonical({'batch':batch,'sourceBatch':source_batch,'sourceRows':len(source_rows),'states':counts,'sha256':digest.hexdigest()}))
    except Exception:
        conn.rollback();raise
    finally:conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--batch',required=True);parser.add_argument('--frozen-through',type=date.fromisoformat,required=True);parser.add_argument('--artifacts',type=Path,required=True)
    args=parser.parse_args();main(args.batch,args.frozen_through,args.artifacts)
