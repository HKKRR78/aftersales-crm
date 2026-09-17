from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from typing import Any

import pymysql


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


def last_complete_saturday(today: date | None = None) -> date:
    anchor = (today or date.today()) - timedelta(days=1)
    return anchor - timedelta(days=(anchor.weekday() - 5) % 7)


def week_windows(n: int = 5) -> list[dict[str, Any]]:
    end = last_complete_saturday()
    windows: list[dict[str, Any]] = []
    for i in reversed(range(n)):
        week_end = end - timedelta(days=i * 7)
        week_start = week_end - timedelta(days=6)
        windows.append({
            "start": week_start,
            "end": week_end + timedelta(days=1),
            "label": f"{week_start:%m%d}-{week_end:%m%d}",
        })
    return windows


def normalize_period(value: str | None) -> str:
    return "progress" if str(value or "").lower() == "progress" else "closed"


def progress_windows(today: date | None = None) -> list[dict[str, Any]]:
    anchor = today or date.today()
    current_start = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
    current_end = anchor
    previous_start = current_start - timedelta(days=7)
    previous_end = current_end - timedelta(days=7)

    def label(prefix: str, start: date, end: date) -> str:
        if start >= end:
            return f"{prefix}（无完整日）"
        return f"{prefix} {start:%m%d}-{(end - timedelta(days=1)):%m%d}"

    return [
        {
            "start": previous_start,
            "end": previous_end,
            "observe_end": previous_end,
            "label": label("上周同期", previous_start, previous_end),
        },
        {
            "start": current_start,
            "end": current_end,
            "observe_end": current_end,
            "label": label("本周同期", current_start, current_end),
        },
    ]


def pct_text(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}%"


def build_weeks(issue_counts: list[int], order_counts: list[int]) -> list[dict[str, Any]]:
    weeks = []
    prev_rate: float | None = None
    for issues, orders in zip(issue_counts, order_counts):
        rate = (issues / orders * 100) if orders else None
        if rate is None or prev_rate is None:
            wow = None
            wow_text = ""
        elif prev_rate == 0 and rate > 0:
            wow = 9999.0
            wow_text = "上期为0"
        elif prev_rate == 0:
            wow = 0.0
            wow_text = "0.00%"
        else:
            wow = (rate - prev_rate) / prev_rate * 100
            wow_text = pct_text(wow)
        weeks.append({
            "issues": int(issues or 0),
            "orders": int(orders or 0),
            "rate": rate,
            "rateText": pct_text(rate) if orders else "",
            "wow": wow,
            "wowText": wow_text,
        })
        prev_rate = rate
    return weeks


def weekly_case(alias: str, windows: list[dict[str, Any]], expr: str = "1") -> str:
    parts = []
    for i, w in enumerate(windows):
        observed = f" AND {alias}.api_created_at < %s" if w.get("observe_end") else ""
        parts.append(f"SUM(CASE WHEN {alias}.wdt_pay_time >= %s AND {alias}.wdt_pay_time < %s{observed} THEN {expr} ELSE 0 END) AS w{i}")
    return ", ".join(parts)


def order_weekly_case(alias: str, windows: list[dict[str, Any]]) -> str:
    parts = []
    for i, _ in enumerate(windows):
        parts.append(
            f"COUNT(DISTINCT CASE WHEN {alias}.pay_time >= %s AND {alias}.pay_time < %s THEN {alias}.origin_order_no END) AS w{i}"
        )
    return ", ".join(parts)


def window_params(windows: list[dict[str, Any]], *, include_observation: bool = True) -> list[Any]:
    params: list[Any] = []
    for w in windows:
        params.extend([w["start"], w["end"]])
        if include_observation and w.get("observe_end"):
            params.append(w["observe_end"])
    return params


def fetch_one_counts(cur, sql: str, params: list[Any], window_count: int) -> list[int]:
    cur.execute(sql, params)
    row = cur.fetchone() or {}
    return [int(row.get(f"w{i}") or 0) for i in range(window_count)]


def daily_order_counts(cur, windows: list[dict[str, Any]], grain_type: str, grain_key: str | None = None) -> dict[str, list[int]]:
    if not any(w["start"] < w["end"] for w in windows):
        return {grain_key or "__all__": [0] * len(windows)}
    sql = """
        SELECT grain_key, stat_date, order_count
        FROM dws_crm_order_daily
        WHERE grain_type=%s AND stat_date >= %s AND stat_date < %s
    """
    params: list[Any] = [grain_type, min(w["start"] for w in windows), max(w["end"] for w in windows)]
    if grain_key is not None:
        sql += " AND grain_key=%s"
        params.append(grain_key)
    cur.execute(sql, params)
    out: dict[str, list[int]] = {}
    for row in cur.fetchall():
        key = str(row.get("grain_key") or "")
        for index, window in enumerate(windows):
            if window["start"] <= row["stat_date"] < window["end"]:
                out.setdefault(key, [0] * len(windows))[index] += int(row.get("order_count") or 0)
                break
    return out


def fetch_order_counts(cur, windows: list[dict[str, Any]], period: str = "closed") -> list[int]:
    if period == "progress":
        expected_days = sum((w["end"] - w["start"]).days for w in windows)
        if expected_days:
            cur.execute("""
                SELECT COUNT(DISTINCT stat_date) AS day_count
                FROM dws_crm_order_daily
                WHERE grain_type='total' AND grain_key='__all__'
                  AND ((stat_date >= %s AND stat_date < %s) OR (stat_date >= %s AND stat_date < %s))
            """, (windows[0]["start"], windows[0]["end"], windows[-1]["start"], windows[-1]["end"]))
            actual_days = int((cur.fetchone() or {}).get("day_count") or 0)
            if actual_days < expected_days:
                raise RuntimeError(f"dws_crm_order_daily incomplete: expected {expected_days} days, got {actual_days}")
        values = daily_order_counts(cur, windows, "total", "__all__")
        return values.get("__all__", [0] * len(windows))
    cur.execute("""
        SELECT week_start, week_end, order_count
        FROM dws_crm_order_weekly
        WHERE grain_type='total' AND grain_key='__all__'
          AND week_start >= %s AND week_end <= %s
    """, (windows[0]["start"], windows[-1]["end"]))
    by_week = {(row["week_start"], row["week_end"]): int(row["order_count"] or 0) for row in cur.fetchall()}
    if len(by_week) >= len(windows):
        return [by_week.get((w["start"], w["end"]), 0) for w in windows]
    sql = f"""
        SELECT {order_weekly_case("o", windows)}
        FROM ods_wdt_stock_out o
        WHERE o.pay_time >= %s AND o.pay_time < %s
          AND o.origin_order_no IS NOT NULL AND o.origin_order_no <> ''
    """
    params = window_params(windows) + [windows[0]["start"], windows[-1]["end"]]
    return fetch_one_counts(cur, sql, params, len(windows))


def fetch_grouped_orders(
    cur,
    windows: list[dict[str, Any]],
    group_col: str,
    period: str = "closed",
    grain_type: str | None = None,
) -> dict[str, list[int]]:
    if grain_type is None:
        grain_type = "merchant_code" if group_col.endswith("merchant_code") else "warehouse"
    if period == "progress":
        return daily_order_counts(cur, windows, grain_type)
    cur.execute("""
        SELECT grain_key, week_start, week_end, order_count
        FROM dws_crm_order_weekly
        WHERE grain_type=%s AND week_start >= %s AND week_end <= %s
    """, (grain_type, windows[0]["start"], windows[-1]["end"]))
    rows = cur.fetchall()
    if rows:
        index = {(w["start"], w["end"]): i for i, w in enumerate(windows)}
        out: dict[str, list[int]] = {}
        for row in rows:
            key = str(row.get("grain_key") or "")
            pos = index.get((row.get("week_start"), row.get("week_end")))
            if pos is None:
                continue
            out.setdefault(key, [0] * len(windows))[pos] = int(row.get("order_count") or 0)
        return out
    sql = f"""
        SELECT {group_col} AS k, {order_weekly_case("o", windows)}
        FROM ods_wdt_stock_out o
        WHERE o.pay_time >= %s AND o.pay_time < %s
          AND {group_col} IS NOT NULL AND {group_col} <> ''
          AND o.origin_order_no IS NOT NULL AND o.origin_order_no <> ''
        GROUP BY {group_col}
    """
    cur.execute(sql, window_params(windows) + [windows[0]["start"], windows[-1]["end"]])
    out: dict[str, list[int]] = {}
    for row in cur.fetchall():
        out[str(row.get("k") or "")] = [int(row.get(f"w{i}") or 0) for i in range(len(windows))]
    return out


def fetch_confirmed_doudian_product_ids(cur) -> set[str]:
    cur.execute("""
        SELECT grain_key
        FROM (
          SELECT grain_key
          FROM dws_crm_order_weekly
          WHERE grain_type='aftersales_product_id' AND grain_key IS NOT NULL AND grain_key <> ''
          UNION
          SELECT grain_key
          FROM dws_crm_order_daily
          WHERE grain_type='aftersales_product_id' AND grain_key IS NOT NULL AND grain_key <> ''
        ) confirmed_doudian_products
    """)
    return {str(row.get("grain_key") or "").strip() for row in cur.fetchall() if row.get("grain_key")}


def split_combo_code(code: str) -> list[str]:
    parts = [p.strip() for p in str(code or "").split("+") if p.strip()]
    return parts if len(parts) > 1 else []


def base_merchant_code(code: str) -> str:
    return re.sub(r"\*\d+$", "", str(code or "").strip())


def series_for_code(code: str, product_orders: dict[str, list[int]]) -> list[int] | None:
    code = str(code or "").strip()
    if code in product_orders:
        return product_orders[code]
    base = base_merchant_code(code)
    if base and base in product_orders:
        return product_orders[base]
    return None


def product_order_series(
    code: str,
    product_orders: dict[str, list[int]],
    total_orders: list[int],
    product_id: str = "",
    platform_product_orders: dict[str, list[int]] | None = None,
) -> list[int]:
    product_id = str(product_id or "").strip()
    if product_id and platform_product_orders and product_id in platform_product_orders:
        return platform_product_orders[product_id]
    exact_or_base = series_for_code(code, product_orders)
    if exact_or_base:
        return exact_or_base
    parts = split_combo_code(code)
    if parts:
        series = [0] * len(total_orders)
        matched = False
        seen: set[str] = set()
        for part in parts:
            key = base_merchant_code(part) or part
            if key in seen:
                continue
            seen.add(key)
            values = series_for_code(part, product_orders)
            if values:
                matched = True
                series = [a + b for a, b in zip(series, values)]
        if matched:
            return series
    return [0] * len(total_orders)


def latest_fields(weeks: list[dict[str, Any]]) -> dict[str, Any]:
    previous = weeks[-2] if len(weeks) >= 2 else {}
    latest = weeks[-1] if weeks else {}
    previous_rate = previous.get("rate")
    current_rate = latest.get("rate")
    rate_delta_pp = current_rate - previous_rate if current_rate is not None and previous_rate is not None else None
    expected_issues = previous_rate / 100 * int(latest.get("orders") or 0) if previous_rate is not None else None
    excess_issues = int(latest.get("issues") or 0) - expected_issues if expected_issues is not None else None
    min_excess = float(os.environ.get("CRM_PROGRESS_ALERT_MIN_EXCESS", "3"))
    min_delta_pp = float(os.environ.get("CRM_PROGRESS_ALERT_MIN_DELTA_PP", "0.3"))
    if rate_delta_pp is None:
        alert_level, alert_rank = "灰色", 0
    elif excess_issues is not None and excess_issues >= min_excess and rate_delta_pp >= min_delta_pp:
        alert_level, alert_rank = "红色", 3
    elif rate_delta_pp > 0:
        alert_level, alert_rank = "黄色", 2
    elif rate_delta_pp < 0:
        alert_level, alert_rank = "绿色", 1
    else:
        alert_level, alert_rank = "灰色", 0
    return {
        "latestIssues": int(latest.get("issues") or 0),
        "latestRate": current_rate,
        "latestWow": latest.get("wow"),
        "latestWowText": latest.get("wowText") or "",
        "total5": sum(int(w.get("issues") or 0) for w in weeks),
        "previousIssues": int(previous.get("issues") or 0),
        "previousOrders": int(previous.get("orders") or 0),
        "previousRate": previous_rate,
        "currentIssues": int(latest.get("issues") or 0),
        "currentOrders": int(latest.get("orders") or 0),
        "currentRate": current_rate,
        "rateDeltaPp": rate_delta_pp,
        "relativeChange": latest.get("wow"),
        "expectedIssues": expected_issues,
        "excessIssues": excess_issues,
        "alertLevel": alert_level,
        "alertRank": alert_rank,
    }


def build_warehouse_row(
    warehouse_code: str,
    warehouse_name: str,
    problem_counts: list[int],
    order_counts: list[int],
) -> dict[str, Any]:
    weeks = build_weeks(problem_counts, order_counts)
    label = f"{warehouse_code} / {warehouse_name}" if warehouse_name else warehouse_code
    item = {
        "warehouse": label,
        "warehouseCode": warehouse_code,
        "warehouseName": warehouse_name,
        "weeks": weeks,
    }
    item.update(latest_fields(weeks))
    return item


def load_mysql_dashboard_data(period: str = "closed", today: date | None = None) -> dict[str, Any]:
    period = normalize_period(period)
    windows = progress_windows(today) if period == "progress" else week_windows(5)
    labels = [w["label"] for w in windows]
    with connect_mysql() as conn:
        with conn.cursor() as cur:
            total_orders = fetch_order_counts(cur, windows, period)
            product_orders = fetch_grouped_orders(cur, windows, "o.merchant_code", period)
            platform_product_orders = fetch_grouped_orders(cur, windows, "product_id", period, "aftersales_product_id")
            confirmed_doudian_product_ids = fetch_confirmed_doudian_product_ids(cur)
            warehouse_orders = fetch_grouped_orders(cur, windows, "o.warehouse_name_raw", period)

            issue_select = weekly_case("a", windows)
            if period == "progress":
                period_conditions = []
                base_params = []
                for window in windows:
                    period_conditions.append("(a.wdt_pay_time >= %s AND a.wdt_pay_time < %s)")
                    base_params.extend([window["start"], window["end"]])
                base_where = "a.source_file_name = 'banniu_api' AND (" + " OR ".join(period_conditions) + ")"
            else:
                base_where = """
                    a.source_file_name = 'banniu_api'
                    AND a.wdt_pay_time >= %s AND a.wdt_pay_time < %s
                """
                base_params = [windows[0]["start"], windows[-1]["end"]]
            cur.execute(f"""
                SELECT
                  COALESCE(NULLIF(a.merchant_code,''), '未填') AS code,
                  COALESCE(NULLIF(MAX(a.product_title),''), '未填') AS name,
                  COALESCE(NULLIF(MAX(a.aftersales_product_id),''), '') AS product_id,
                  COALESCE(NULLIF(a.problem1,''), '未分类') AS p1,
                  COALESCE(NULLIF(a.problem2,''), '') AS p2,
                  COALESCE(NULLIF(a.problem3,''), '') AS p3,
                  COALESCE(NULLIF(a.rule_category,''), COALESCE(NULLIF(a.problem1,''), '未分类')) AS category,
                  {issue_select}
                FROM ods_banniu_aftersales a
                WHERE {base_where}
                GROUP BY code, p1, p2, p3, category
            """, window_params(windows) + base_params)
            rows = []
            for row in cur.fetchall():
                counts = [int(row.get(f"w{i}") or 0) for i in range(len(windows))]
                code = str(row.get("code") or "")
                product_id = str(row.get("product_id") or "").strip()
                orders = product_order_series(
                    code,
                    product_orders,
                    total_orders,
                    product_id,
                    platform_product_orders,
                )
                weeks = build_weeks(counts, orders)
                item = {
                    "code": code,
                    "name": row.get("name") or "",
                    "product_id": product_id,
                    "doudian_product_id": product_id if product_id in confirmed_doudian_product_ids else "",
                    "p1": row.get("p1") or "",
                    "p2": row.get("p2") or "",
                    "p3": row.get("p3") or "",
                    "category": row.get("category") or "",
                    "weeks": weeks,
                }
                item.update(latest_fields(weeks))
                rows.append(item)

            cur.execute(f"""
                SELECT
                  COALESCE(NULLIF(a.source_warehouse_code,''), '未填') AS warehouse_code,
                  COALESCE(NULLIF(MAX(m.warehouse_name_raw),''), '') AS warehouse_name,
                  {weekly_case("a", windows, "CASE WHEN a.problem1 = '库房问题' THEN 1 ELSE 0 END")}
                FROM ods_banniu_aftersales a
                LEFT JOIN dim_crm_warehouse_map m
                  ON m.source_warehouse_code = a.source_warehouse_code
                 AND m.is_active = 1
                WHERE {base_where}
                GROUP BY warehouse_code
            """, window_params(windows) + base_params)
            warehouse_rows = []
            for row in cur.fetchall():
                counts = [int(row.get(f"w{i}") or 0) for i in range(len(windows))]
                warehouse_code = row.get("warehouse_code") or ""
                warehouse_name = row.get("warehouse_name") or ""
                orders = warehouse_orders.get(str(warehouse_name)) if warehouse_name else None
                warehouse_rows.append(build_warehouse_row(
                    str(warehouse_code),
                    str(warehouse_name),
                    counts,
                    orders if orders is not None else [0] * len(windows),
                ))

            if period == "progress":
                rows.sort(key=lambda r: (-r["alertRank"], -(r["excessIssues"] or 0), -r["latestIssues"], r["code"], r["p1"], r["p2"], r["p3"]))
                warehouse_rows.sort(key=lambda r: (-r["alertRank"], -(r["excessIssues"] or 0), -r["latestIssues"], r["warehouse"]))
            else:
                rows.sort(key=lambda r: (-r["latestIssues"], -r["total5"], r["code"], r["p1"], r["p2"], r["p3"]))
                warehouse_rows.sort(key=lambda r: (-r["latestIssues"], -r["total5"], r["warehouse"]))

            latest_issue_total = sum(w[-1]["issues"] for w in (r["weeks"] for r in rows))
            total_week_metrics = latest_fields(build_weeks(
                [sum(r["weeks"][index]["issues"] for r in rows) for index in range(len(windows))],
                total_orders,
            ))
            deteriorated = sum(1 for r in rows if (r["weeks"][-1].get("wow") or 0) > 0)
            zero_prev = sum(1 for r in rows if r["weeks"][-1].get("wowText") == "上期为0")
            red_alerts = sum(1 for r in rows if r.get("alertLevel") == "红色")
            cur.execute("""
                SELECT MAX(api_synced_at) AS synced_at, COUNT(*) AS api_rows
                FROM ods_banniu_aftersales
                WHERE source_file_name = 'banniu_api'
            """)
            source_row = cur.fetchone() or {}
            missing_created_at = 0
            if period == "progress":
                conditions = []
                condition_params: list[Any] = []
                for window in windows:
                    conditions.append("(wdt_pay_time >= %s AND wdt_pay_time < %s)")
                    condition_params.extend([window["start"], window["end"]])
                cur.execute(f"""
                    SELECT COUNT(*) AS missing_count
                    FROM ods_banniu_aftersales
                    WHERE source_file_name='banniu_api'
                      AND api_created_at IS NULL
                      AND ({' OR '.join(conditions)})
                """, condition_params)
                missing_created_at = int((cur.fetchone() or {}).get("missing_count") or 0)

    filters = {
        "p1": sorted({r["p1"] for r in rows if r.get("p1")}),
        "p2": sorted({r["p2"] for r in rows if r.get("p2")}),
    }
    return {
        "weeks": labels,
        "orderWeeks": total_orders,
        "rows": rows,
        "warehouseRows": warehouse_rows,
        "filters": filters,
        "kpis": {
            "latest": labels[-1] if labels else "",
            "rowCount": len(rows),
            "totalLatest": latest_issue_total,
            "deteriorated": deteriorated,
            "zeroPrev": zero_prev,
            "redAlerts": red_alerts,
            "currentOrders": total_week_metrics["currentOrders"],
            "currentRate": total_week_metrics["currentRate"],
            "previousRate": total_week_metrics["previousRate"],
            "rateDeltaPp": total_week_metrics["rateDeltaPp"],
            "relativeChange": total_week_metrics["relativeChange"],
            "excessIssues": total_week_metrics["excessIssues"],
        },
        "periodMode": period,
        "periodMeta": {
            "start": str(windows[-1]["start"]),
            "end": str(windows[-1]["end"]),
            "comparisonStart": str(windows[0]["start"]),
            "comparisonEnd": str(windows[0]["end"]),
            "completedDays": (windows[-1]["end"] - windows[-1]["start"]).days,
            "missingCreatedAt": missing_created_at,
        },
        "source": {
            "currentPeriod": labels[-1] if labels else "",
            "orderKey": "ods_wdt_stock_out 按付款时间，商品分母按商家编码订单去重",
            "aftersalesKey": "班牛 API task_id + 商品行",
            "sourceType": "mysql",
            "syncedAt": str(source_row.get("synced_at") or ""),
            "apiRows": int(source_row.get("api_rows") or 0),
            "warehouseOrderNote": "仓库库房问题率仅统计 problem1=库房问题，并使用 dim_crm_warehouse_map 将班牛仓库编码映射到 WDT 仓库名作为订单分母；未映射或无仓库订单分母时不计算比率",
            "periodMode": period,
        },
    }
