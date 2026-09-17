#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date

from crm_schema import connect_mysql


SUMMARY_SQL = """
SELECT source_system, DATE(api_created_at) AS created_date,
       COALESCE(shop_name,'') AS shop_name, COALESCE(problem1,'未分类') AS problem1,
       COUNT(*) AS fact_rows
FROM ods_crm_aftersales
WHERE included_in_analytics=1 AND api_created_at >= %s AND api_created_at < %s
GROUP BY source_system, DATE(api_created_at), shop_name, problem1
ORDER BY created_date, source_system, shop_name, problem1
"""

DUPLICATE_SQL = """
SELECT 'order' AS match_level, order_no, '' AS sub_order_no, '' AS product_id,
       GROUP_CONCAT(DISTINCT source_system ORDER BY source_system) AS sources,
       COUNT(*) AS fact_rows,
       MIN(api_created_at), MAX(api_created_at)
FROM ods_crm_aftersales
WHERE included_in_analytics=1 AND api_created_at >= %s AND api_created_at < %s
  AND order_no IS NOT NULL AND order_no <> ''
GROUP BY order_no
HAVING COUNT(DISTINCT source_system) > 1
UNION ALL
SELECT 'order_suborder', order_no, COALESCE(sub_order_no,''), '',
       GROUP_CONCAT(DISTINCT source_system ORDER BY source_system),
       COUNT(*), MIN(api_created_at), MAX(api_created_at)
FROM ods_crm_aftersales
WHERE included_in_analytics=1 AND api_created_at >= %s AND api_created_at < %s
  AND order_no IS NOT NULL AND order_no <> ''
GROUP BY order_no, COALESCE(sub_order_no,'')
HAVING COUNT(DISTINCT source_system) > 1
UNION ALL
SELECT 'order_suborder_product', order_no, COALESCE(sub_order_no,''), COALESCE(aftersales_product_id,''),
       GROUP_CONCAT(DISTINCT source_system ORDER BY source_system),
       COUNT(*), MIN(api_created_at), MAX(api_created_at)
FROM ods_crm_aftersales
WHERE included_in_analytics=1 AND api_created_at >= %s AND api_created_at < %s
  AND order_no IS NOT NULL AND order_no <> ''
GROUP BY order_no, COALESCE(sub_order_no,''), COALESCE(aftersales_product_id,'')
HAVING COUNT(DISTINCT source_system) > 1
ORDER BY match_level, fact_rows DESC, order_no
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="输出班牛与新工单来源的交接对账")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--approve-batch", help="人工完成交接核对后，启用新工单来源并批准指定成功批次")
    parser.add_argument("--approved-by", help="与 --approve-batch 同时提供，记录审批人")
    parser.add_argument("--cutover-date", help="与 --approve-batch 同时提供；班牛截止、新接口起始日期（YYYY-MM-DD）")
    args = parser.parse_args()
    start, end = date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)
    if start >= end:
        raise SystemExit("start-date 必须早于 end-date")
    cutover = None
    if args.approve_batch:
        if not args.approved_by or not args.cutover_date:
            raise SystemExit("--approve-batch 必须同时提供 --approved-by 和 --cutover-date")
        cutover = date.fromisoformat(args.cutover_date)
    conn = connect_mysql()
    try:
        with conn.cursor() as cur:
            cur.execute(SUMMARY_SQL, (start, end))
            summary = cur.fetchall()
            cur.execute(DUPLICATE_SQL, (start, end, start, end, start, end))
            duplicates = cur.fetchall()
            if args.approve_batch:
                cur.execute(
                    "SELECT status FROM etl_crm_ticket_batches WHERE batch_id=%s FOR UPDATE",
                    (args.approve_batch,),
                )
                batch = cur.fetchone()
                if not batch or batch[0] != "published":
                    raise SystemExit("指定批次不存在或尚未成功发布")
                cur.execute(
                    "UPDATE etl_crm_ticket_batches SET reconciliation_status='approved' WHERE batch_id=%s",
                    (args.approve_batch,),
                )
                cur.execute(
                    "SELECT source_system FROM dim_crm_source_state WHERE source_system IN ('banniu','ticket_service') FOR UPDATE"
                )
                source_systems = {row[0] for row in cur.fetchall()}
                if source_systems != {"banniu", "ticket_service"}:
                    raise SystemExit("来源控制记录不完整，请先执行 crm_schema.py")
                cur.execute(
                    """UPDATE dim_crm_source_state
                       SET analytics_enabled=1, analytics_start_at=NULL, analytics_end_at=%s,
                           approved_by=%s, approved_at=NOW(), note='交接日前班牛历史'
                       WHERE source_system='banniu'""",
                    (cutover, args.approved_by),
                )
                cur.execute(
                    """UPDATE dim_crm_source_state
                       SET analytics_enabled=1, analytics_start_at=%s, analytics_end_at=NULL,
                           approved_by=%s, approved_at=NOW(), note='交接日起新工单来源'
                       WHERE source_system='ticket_service'""",
                    (cutover, args.approved_by),
                )
                conn.commit()
    finally:
        conn.close()
    if args.format == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(["match_level", "order_no", "sub_order_no", "product_id", "sources", "fact_rows", "first_created_at", "last_created_at"])
        writer.writerows(duplicates)
    else:
        print(json.dumps({
            "range": [str(start), str(end)],
            "summary": [list(row) for row in summary],
            "suspected_cross_source_duplicates": [list(row) for row in duplicates],
            "duplicate_policy": "review_only_no_automatic_merge",
            "approved_batch": args.approve_batch,
            "cutover_date": args.cutover_date,
        }, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
