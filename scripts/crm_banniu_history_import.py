#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime

from crm_schema import connect_mysql


COUNT_SQL = "SELECT COUNT(*) FROM ods_banniu_aftersales"

INSERT_SQL = """
INSERT INTO ods_crm_aftersales (
  source_system, source_ticket_id, source_item_id, aftersales_business_key,
  ticket_no, source_status, item_type, included_in_analytics,
  shop_name, platform, order_no, sub_order_no, logistics_no,
  problem1, problem2, problem3, problem_path, handle_method, amount,
  product_title, aftersales_product_id, buy_qty, sku_attr, merchant_code,
  source_warehouse_code, source_warehouse_name, source_logistics_company, refund_apply_time, paid_amount,
  wdt_pay_time, api_created_at, api_updated_at, api_synced_at,
  match_status, matched_by, raw_payload, import_batch
)
SELECT
  'banniu',
  COALESCE(NULLIF(api_task_id,''), NULLIF(aftersales_id,''), CONCAT('legacy-', CAST(id AS CHAR))),
  COALESCE(NULLIF(api_child_key,''), CAST(id AS CHAR)),
  CONCAT('banniu:', aftersales_business_key),
  CAST(aftersales_id AS CHAR), NULL, 'order',
  CASE WHEN source_file_name='banniu_api' THEN 1 ELSE 0 END,
  shop_name, platform, order_no,
  NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_payload, '$.child."13175"')), 'null'),
  logistics_no, problem1, problem2, problem3, problem_path, handle_method, amount,
  product_title, aftersales_product_id, buy_qty, sku_attr, merchant_code,
  source_warehouse_code, warehouse_name, source_logistics_company,
  STR_TO_DATE(NULLIF(TRIM(refund_apply_time), ''), '%%Y-%%m-%%d %%H:%%i:%%s'),
  CAST(NULLIF(TRIM(paid_amount),'') AS DECIMAL(18,4)),
  wdt_pay_time, api_created_at, api_updated_at, COALESCE(api_synced_at, NOW()),
  match_status, matched_by, raw_payload, %s
FROM ods_banniu_aftersales
ON DUPLICATE KEY UPDATE
  source_ticket_id=VALUES(source_ticket_id), source_item_id=VALUES(source_item_id),
  included_in_analytics=VALUES(included_in_analytics),
  shop_name=VALUES(shop_name), platform=VALUES(platform), order_no=VALUES(order_no),
  sub_order_no=VALUES(sub_order_no), logistics_no=VALUES(logistics_no),
  problem1=VALUES(problem1), problem2=VALUES(problem2), problem3=VALUES(problem3),
  problem_path=VALUES(problem_path), handle_method=VALUES(handle_method), amount=VALUES(amount),
  product_title=VALUES(product_title), aftersales_product_id=VALUES(aftersales_product_id),
  buy_qty=VALUES(buy_qty), sku_attr=VALUES(sku_attr), merchant_code=VALUES(merchant_code),
  source_warehouse_code=VALUES(source_warehouse_code), source_warehouse_name=VALUES(source_warehouse_name),
  source_logistics_company=VALUES(source_logistics_company),
  refund_apply_time=VALUES(refund_apply_time), paid_amount=VALUES(paid_amount),
  wdt_pay_time=VALUES(wdt_pay_time), api_created_at=VALUES(api_created_at),
  api_updated_at=VALUES(api_updated_at), api_synced_at=VALUES(api_synced_at),
  match_status=VALUES(match_status), matched_by=VALUES(matched_by),
  raw_payload=VALUES(raw_payload), import_batch=VALUES(import_batch)
"""


def counts(conn) -> tuple[int, int]:
    with conn.cursor() as cur:
        cur.execute(COUNT_SQL)
        source = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM ods_crm_aftersales WHERE source_system='banniu'")
        imported = int(cur.fetchone()[0])
    return source, imported


def parity(conn) -> tuple[tuple, tuple]:
    common_columns = """
      COUNT(*), SUM(api_created_at IS NOT NULL), SUM(wdt_pay_time IS NOT NULL),
      SUM(COALESCE(merchant_code,'') <> ''), SUM(COALESCE(aftersales_product_id,'') <> ''),
      SUM(COALESCE(problem1,'') <> ''), SUM(COALESCE(source_warehouse_code,'') <> '')
    """
    with conn.cursor() as cur:
        cur.execute(f"SELECT {common_columns}, SUM(source_file_name='banniu_api') FROM ods_banniu_aftersales")
        source = tuple(cur.fetchone())
        cur.execute(f"SELECT {common_columns}, SUM(included_in_analytics=1) FROM ods_crm_aftersales WHERE source_system='banniu'")
        imported = tuple(cur.fetchone())
    return source, imported


def main() -> int:
    parser = argparse.ArgumentParser(description="一次性导入班牛历史到统一售后事实表")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    batch = f"banniu_history_{datetime.now():%Y%m%d_%H%M%S}"
    conn = connect_mysql()
    try:
        before = counts(conn)
        if not args.dry_run:
            with conn.cursor() as cur:
                cur.execute(INSERT_SQL, (batch,))
            after = counts(conn)
            source_parity, imported_parity = parity(conn)
            if after[1] != before[0] or source_parity != imported_parity:
                raise RuntimeError(f"班牛历史导入核对失败: source={source_parity} imported={imported_parity}")
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT MIN(COALESCE(api_created_at, wdt_pay_time)),
                           DATE_ADD(MAX(COALESCE(api_created_at, wdt_pay_time)), INTERVAL 1 SECOND),
                           COUNT(DISTINCT source_ticket_id)
                    FROM ods_crm_aftersales
                    WHERE source_system='banniu'
                """)
                coverage_start, coverage_end, ticket_count = cur.fetchone()
                cur.execute("""
                    INSERT INTO etl_crm_ticket_batches (
                      batch_id, source_system, coverage_start, coverage_end, status, reconciliation_status,
                      pages_read, tickets_read, fact_rows, new_rows, changed_rows, missing_rows,
                      started_at, completed_at
                    ) VALUES (%s, 'banniu', %s, %s, 'published', 'approved', 0, %s, %s, %s, 0, 0, NOW(), NOW())
                """, (batch, coverage_start, coverage_end, ticket_count, after[1], max(0, after[1] - before[1])))
            conn.commit()
        else:
            after = before
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(json.dumps({"batch": batch, "dry_run": args.dry_run, "source_rows": before[0], "imported_before": before[1], "imported_after": after[1]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
