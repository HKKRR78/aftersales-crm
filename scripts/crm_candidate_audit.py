#!/usr/bin/env python3
"""Export record-level candidate differences without changing report pointers."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from crm_schema import connect_mysql
from crm_report_model import canonical
from crm_sales_sources import query


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fieldnames)
        writer.writeheader();writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(candidate, baseline, output, mapped=''):
    conn=connect_mysql()
    try:
        batches=query(conn,"SELECT batch_id,status,source_batch_id,summary_json FROM crm_report_batch WHERE batch_id IN (%s,%s)",(candidate,baseline))
        by_id={row['batch_id']:row for row in batches}
        if set(by_id)!={candidate,baseline}:raise ValueError('candidate or baseline batch unavailable')
        summary=json.loads(by_id[candidate]['summary_json'])
        candidate_rows=query(conn,"SELECT * FROM crm_report_issue WHERE batch_id=%s ORDER BY created_at,issue_key",(candidate,))
        baseline_rows={row['issue_key']:row for row in query(conn,"SELECT * FROM crm_report_issue WHERE batch_id=%s",(baseline,))}
        assignment=[]
        for row in candidate_rows:
            old=baseline_rows.get(row['issue_key'],{})
            evidence=json.loads(row['evidence_json'])
            assignment.append({
                'issue_key':row['issue_key'],'source_fact_id':row['source_fact_id'],'source_ticket_id':row['source_ticket_id'],
                'created_at':row['created_at'],'included_operating':row['included_operating'],
                'old_code':old.get('merchant_code',''),'new_code':row['merchant_code'],
                'old_status':old.get('match_status','not_in_baseline'),'new_status':row['match_status'],
                'old_reason':old.get('match_reason','not_in_baseline'),'new_reason':row['match_reason'],
                'candidate_sales_lines':canonical(evidence.get('candidateSalesLines',[])),
                'evidence_hits':canonical(evidence.get('evidenceHits',[])),
                'source_refs':canonical(evidence.get('sourceRefs',[])),
                'changed':int(not old or any(old.get(key)!=row[key] for key in ('merchant_code','match_status','match_reason'))),
            })
        assignment_path=output/'售后归属清单.csv'
        assignment_sha=write_csv(assignment_path,list(assignment[0]),assignment)

        periods={(item['start'],item['end']) for item in summary['releaseScope']['requiredPeriods']}
        codes=sorted({row['merchant_code'] for row in candidate_rows if row['included_operating'] and row['merchant_code']})
        metric={(str(row['period_start']),str(row['period_end']),row['merchant_code']):row for row in query(conn,
            'SELECT * FROM crm_report_product_metric WHERE batch_id=%s',(candidate,))} if summary.get('productMetricLayer') else {}
        orders={(str(row['period_start']),str(row['period_end']),row['grain_key']):row for row in query(conn,
            "SELECT * FROM crm_report_orders WHERE batch_id=%s AND grain_type='merchant_code'",(candidate,))}
        states={(str(row['period_start']),str(row['period_end']),row['grain_key']):row for row in query(conn,
            "SELECT * FROM crm_report_denominator_status WHERE batch_id=%s AND grain_type='merchant_code'",(candidate,))}
        denominator=[]
        for start,end in sorted(periods):
            global_state=states.get((start,end,''),{})
            for code in codes:
                product_metric=metric.get((start,end,code))
                if product_metric:
                    denominator.append({'merchant_code':code,'period_start':start,'period_end':end,
                        'state':product_metric['sales_status'],'order_count':product_metric['order_count'] if product_metric['order_count'] is not None else '',
                        'sales_qty':product_metric['sales_qty'] if product_metric['sales_qty'] is not None else '',
                        'reason':product_metric['reason'],'source_batch_id':product_metric['source_batch'],
                        'source_digest':product_metric['evidence_hash']})
                else:
                    value=orders.get((start,end,code));specific=states.get((start,end,code),{})
                    complete=bool(global_state.get('is_complete')) and specific.get('is_complete',1)!=0
                    denominator.append({'merchant_code':code,'period_start':start,'period_end':end,
                        'state':'value' if complete and value else 'verified_zero' if complete else 'uncovered',
                        'order_count':value['order_count'] if complete and value else '',
                        'sales_qty':value['sales_qty'] if complete and value else '',
                        'reason':specific.get('reason') or global_state.get('reason') or 'denominator_state_missing',
                        'source_batch_id':by_id[candidate]['source_batch_id'],
                        'source_digest':summary.get('salesFactSha256','')})
        denominator_path=output/'商品分母清单.csv'
        denominator_sha=write_csv(denominator_path,list(denominator[0]),denominator)

        week=[row for row in candidate_rows if str(row['created_at'])[:10]>='2026-09-06' and str(row['created_at'])[:10]<'2026-09-13']
        target_ids={61713,62000,61958,118281}
        original_unmatched=[row for row in baseline_rows.values() if row['included_operating'] and not row['merchant_code']
            and '2026-09-06'<=str(row['created_at'])[:10]<'2026-09-13']
        mapped_rows={row['issue_key']:row for row in query(conn,'SELECT * FROM crm_report_issue WHERE batch_id=%s',(mapped,))} if mapped else {}
        original_33=[{'source_fact_id':row['source_fact_id'],'source_ticket_id':row['source_ticket_id'],
            'mapped_code':mapped_rows.get(row['issue_key'],{}).get('merchant_code',''),
            'mapped_reason':mapped_rows.get(row['issue_key'],{}).get('match_reason',''),
            'new_code':next((item['merchant_code'] for item in candidate_rows if item['issue_key']==row['issue_key']),''),
            'new_reason':next((item['match_reason'] for item in candidate_rows if item['issue_key']==row['issue_key']),'')}
            for row in original_unmatched]
        result={'candidate':candidate,'baseline':baseline,'candidateStatus':by_id[candidate]['status'],
            'currentPointer':query(conn,'SELECT batch_id FROM crm_report_current WHERE singleton=1')[0]['batch_id'],
            'week0906':{'total':len(week),'operating':sum(r['included_operating'] for r in week),
                'matchedOperating':sum(r['included_operating'] and bool(r['merchant_code']) for r in week),
                'unmatchedOperating':sum(r['included_operating'] and not r['merchant_code'] for r in week),
                'excludedUnmatched':sum(not r['included_operating'] and not r['merchant_code'] for r in week),
                'matchReasons':dict(Counter(r['match_reason'] for r in week))},
            'originalWeekUnmatched':original_33,
            'targets':[{'source_fact_id':r['source_fact_id'],'source_ticket_id':r['source_ticket_id'],'included_operating':r['included_operating'],
                'raw_code':r['raw_code'],'merchant_code':r['merchant_code'],'status':r['match_status'],'reason':r['match_reason']}
                for r in candidate_rows if r['source_fact_id'] in target_ids or r['source_ticket_id']=='9515'],
            'assignment':{'path':str(assignment_path),'rows':len(assignment),'changed':sum(r['changed'] for r in assignment),'sha256':assignment_sha},
            'denominator':{'path':str(denominator_path),'rows':len(denominator),'states':dict(Counter(r['state'] for r in denominator)),'sha256':denominator_sha}}
        (output/'候选核算摘要.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,default=str))
    finally:
        conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--candidate',required=True);parser.add_argument('--baseline',required=True);parser.add_argument('--mapped',default='');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();main(args.candidate,args.baseline,args.output,args.mapped)
