#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import date

import pymysql


VALID_CATEGORIES = ("快递问题", "库房问题", "买家问题", "产品问题", "运营问题")


def connect_mysql():
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER") or os.environ.get("DB_USER") or "root",
        password=os.environ.get("MYSQL_PASSWORD") or os.environ.get("DB_PASSWORD") or "",
        database=os.environ.get("MYSQL_DATABASE") or os.environ.get("DB_NAME") or "ecom_profit",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def classification_cte(date_filter: str) -> str:
    categories = ",".join(["%s"] * len(VALID_CATEGORIES))
    return f"""
      WITH classified AS (
        SELECT
          a.source_system,
          COALESCE(NULLIF(a.problem1,''), '未分类') AS problem1,
          COALESCE(NULLIF(a.problem2,''), '未填写') AS problem2,
          COALESCE(NULLIF(a.problem3,''), '未填写') AS problem3,
          a.wdt_pay_time,
          a.api_created_at,
          CASE WHEN old_rule.include_business_exception=1 AND old_rule.is_enabled=1 THEN 1 ELSE 0 END AS old_included,
          CASE
            WHEN COALESCE(NULLIF(a.problem1,''), '未分类') NOT IN ({categories}) THEN 'unclassified'
            WHEN EXISTS (
              SELECT 1 FROM dim_crm_exclusion_rule x
              WHERE x.is_enabled=1
                AND x.problem1=COALESCE(NULLIF(a.problem1,''), '未分类')
                AND x.problem2=COALESCE(NULLIF(a.problem2,''), '未填写')
                AND (x.problem3_pattern='*' OR x.problem3_pattern=COALESCE(NULLIF(a.problem3,''), '未填写'))
            ) THEN 'excluded'
            ELSE 'included'
          END AS new_status
        FROM ods_crm_aftersales a
        LEFT JOIN dim_crm_problem_rule old_rule
          ON old_rule.problem1=COALESCE(NULLIF(a.problem1,''), '未分类')
         AND old_rule.problem2=COALESCE(NULLIF(a.problem2,''), '未填写')
         AND old_rule.problem3=COALESCE(NULLIF(a.problem3,''), '未填写')
        WHERE a.included_in_analytics=1
          AND EXISTS (
            SELECT 1 FROM dim_crm_source_state s
            WHERE s.source_system=a.source_system AND s.analytics_enabled=1
              AND (s.analytics_start_at IS NULL OR COALESCE(a.api_created_at,a.wdt_pay_time) >= s.analytics_start_at)
              AND (s.analytics_end_at IS NULL OR COALESCE(a.api_created_at,a.wdt_pay_time) < s.analytics_end_at)
          )
          {date_filter}
      )
    """


def query(conn, select_sql: str, start: date | None, end: date | None):
    date_filter = ""
    params: list[object] = list(VALID_CATEGORIES)
    if start:
        date_filter += " AND COALESCE(a.api_created_at,a.wdt_pay_time) >= %s"
        params.append(start)
    if end:
        date_filter += " AND COALESCE(a.api_created_at,a.wdt_pay_time) < %s"
        params.append(end)
    with conn.cursor() as cur:
        cur.execute(classification_cte(date_filter) + select_sql, params)
        return list(cur.fetchall())


def main() -> int:
    parser = argparse.ArgumentParser(description="只读比较旧问题规则与五大分类加可剔除规则的统计差异")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    args = parser.parse_args()
    start = date.fromisoformat(args.start_date) if args.start_date else None
    end = date.fromisoformat(args.end_date) if args.end_date else None
    if start and end and start >= end:
        raise SystemExit("start-date 必须早于 end-date")

    conn = connect_mysql()
    try:
        overall = query(conn, """
          SELECT COUNT(*) AS fact_rows,
                 SUM(old_included) AS old_operating,
                 SUM(new_status='included') AS new_operating,
                 SUM(new_status='excluded') AS new_excluded,
                 SUM(new_status='unclassified') AS new_unclassified
          FROM classified
        """, start, end)[0]
        by_source_and_category = query(conn, """
          SELECT source_system, problem1,
                 COUNT(*) AS fact_rows,
                 SUM(old_included) AS old_operating,
                 SUM(new_status='included') AS new_operating,
                 SUM(new_status='excluded') AS new_excluded,
                 SUM(new_status='unclassified') AS new_unclassified
          FROM classified
          GROUP BY source_system, problem1
          ORDER BY source_system, problem1
        """, start, end)
        by_path = query(conn, """
          SELECT problem1, problem2, problem3,
                 COUNT(*) AS fact_rows,
                 SUM(old_included) AS old_operating,
                 SUM(new_status='included') AS new_operating,
                 SUM(new_status='included')-SUM(old_included) AS operating_delta,
                 MAX(new_status) AS new_status
          FROM classified
          GROUP BY problem1, problem2, problem3
          HAVING operating_delta<>0 OR new_status<>'included'
          ORDER BY ABS(operating_delta) DESC, problem1, problem2, problem3
        """, start, end)
    finally:
        conn.close()

    overall["operating_delta"] = int(overall.get("new_operating") or 0) - int(overall.get("old_operating") or 0)
    print(json.dumps({
        "range": [str(start) if start else None, str(end) if end else None],
        "scope": "当前来源门禁内的全部可统计事实",
        "overall": overall,
        "by_source_and_category": by_source_and_category,
        "changed_or_non_operating_paths": by_path,
    }, ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
