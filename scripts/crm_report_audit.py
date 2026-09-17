"""Read-only real-source reconciliation. Writes only a local evidence artifact.

This is not a publisher. A successful read does not assert source completeness.
"""
from __future__ import annotations

import argparse
import gzip
import os
from collections import Counter
from datetime import date
from pathlib import Path

from crm_schema import connect_mysql
from crm_report_model import canonical, resolve_sale, text
from crm_sales_sources import Shops, query, match_native_orders


def audit(conn, end, output):
    shops = Shops(conn)
    from crm_report_build import current_facts
    rows = query(conn, "SELECT a.* FROM ods_crm_aftersales a WHERE a.included_in_analytics=1 AND a.api_created_at < %s", (end,))
    facts, retired = current_facts(conn,end)
    sales_counts, errors, source_issues = Counter(), [], Counter()
    candidates=match_native_orders(conn,shops,facts,
        progress=lambda p,s,n: print(canonical(dict(platform=p,shop=s,requested_orders=n)),flush=True))
    for sale_rows in candidates.values():
        for sale in sale_rows.values():
            sales_counts[sale['platform']]+=1
            if not sale['code']:source_issues[sale['platform']+'/empty_code']+=1
    results=[]
    for fact in facts:
        shop=fact['_shop']
        sales=list(candidates.get((*shop,text(fact['order_no'])),{}).values()) if shop else []
        # Exact-order enumeration is now complete. Parent-only attribution
        # still requires reconciliation with the official source manifest.
        complete=bool(sales) and all(s.get('original_order_complete') for s in sales)
        matched=resolve_sale(fact,sales,order_complete=complete) if shop else dict(status='missing',reason='shop_identity_unverified',code='',sales=[])
        results.append(dict(id=fact['id'],source=fact['source_system'],created_at=str(fact['api_created_at']),
                            shop=fact['shop_name'],platform=shop[0] if shop else fact['platform'],
                            status=matched['status'],reason=matched['reason'],old_code=fact['merchant_code'],
                            code=matched['code'],candidate_codes=sorted({s['code'] for s in sales}),
                            evidence=[s['evidence'] for s in matched['sales']]))
    summary=dict(read_only=True,source_created_before=end,native_orders_scope='all exact referenced orders without payment cutoff',source_fact_count=len(rows),
                 effective_fact_count=len(facts),retired_fact_ids=retired,sales_rows=dict(sales_counts),
                 source_issues=dict(source_issues),errors=errors,
                 match_reasons=dict(Counter(r['reason'] for r in results)),
                 changed_codes=sum(r['status']=='verified' and r['old_code']!=r['code'] for r in results))
    output.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(output,'wt',encoding='utf-8') as stream:
        stream.write(canonical(dict(summary=summary,issues=results)))
    os.chmod(output,0o600)
    print(canonical(summary),flush=True)
    if errors:
        raise RuntimeError('source audit incomplete; see evidence errors')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--end',type=date.fromisoformat,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    c=connect_mysql()
    try:
        with c.cursor() as cursor:
            cursor.execute('SET SESSION MAX_EXECUTION_TIME=30000')
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cursor.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        audit(c,args.end,args.output)
    finally:
        c.rollback();c.close()
