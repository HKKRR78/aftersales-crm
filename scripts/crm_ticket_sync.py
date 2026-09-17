#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from crm_schema import connect_mysql


SOURCE_SYSTEM = "ticket_service"
SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_BASE_URL = "https://csc.yuyuai.cn"
ANALYTICS_ITEM_TYPES = {"order", "missing", "wrong", "extra"}


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid datetime: {text}") from exc
    if parsed.tzinfo:
        parsed = parsed.astimezone(SHANGHAI).replace(tzinfo=None)
    return parsed


def decimal_value(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal: {value}") from exc


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_key(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()


def request_json(
    base_url: str,
    token: str,
    params: dict[str, Any],
    *,
    attempts: int = 3,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    url = f"{base_url.rstrip('/')}/api/v1/tickets/export/json?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    for attempt in range(1, attempts + 1):
        try:
            with opener(request, timeout=30) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or payload.get("success") is not True or str(payload.get("code")) != "0":
                raise RuntimeError("ticket export returned an invalid success envelope")
            if not isinstance(payload.get("data"), list):
                raise RuntimeError("ticket export returned no data list")
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code in {400, 401, 403}:
                raise RuntimeError(f"ticket export rejected request with HTTP {exc.code}") from exc
            if exc.code not in {429, 503} or attempt == attempts:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            sleep(max(7.0, float(retry_after or 0)))
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            if attempt == attempts:
                raise
            sleep(7.0)
    raise RuntimeError("ticket export retry loop exhausted")


def normalize_ticket(ticket: dict, batch_id: str, synced_at: datetime) -> tuple[dict, list[dict]]:
    ticket_id = "" if ticket.get("id") is None else str(ticket["id"]).strip()
    if not ticket_id:
        raise ValueError("ticket is missing id")
    created_at = parse_datetime(ticket.get("createdAt"))
    if created_at is None:
        raise ValueError(f"ticket {ticket_id} is missing source creation time")
    updated_at = parse_datetime(ticket.get("updatedAt"))
    payload_text = canonical_json(ticket)
    raw = {
        "source_system": SOURCE_SYSTEM,
        "source_ticket_id": ticket_id,
        "ticket_no": str(ticket.get("ticketNo") or ""),
        "source_created_at": created_at,
        "source_updated_at": updated_at,
        "source_version": ticket.get("version"),
        "content_hash": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
        "raw_payload": payload_text,
        "import_batch": batch_id,
        "synced_at": synced_at,
    }
    items = ticket.get("skuItems")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ValueError(f"ticket {ticket_id} skuItems is not a list")
    selected = items if items else [{}]
    facts: list[dict] = []
    seen_item_ids: set[str] = set()
    for index, item in enumerate(selected, 1):
        if items and item.get("id") is None:
            raise ValueError(f"ticket {ticket_id} item {index} is missing id")
        source_item_id = "__ticket__" if not items else str(item["id"]).strip()
        if not source_item_id:
            raise ValueError(f"ticket {ticket_id} item {index} has an empty id")
        if source_item_id in seen_item_ids:
            raise ValueError(f"ticket {ticket_id} has duplicate item id {source_item_id}")
        seen_item_ids.add(source_item_id)
        item_warehouse = str(item.get("warehouseCode") or "").strip()
        ticket_warehouse = str(ticket.get("wdtWarehouseNo") or "").strip()
        warehouse_conflict = bool(item_warehouse and ticket_warehouse and item_warehouse != ticket_warehouse)
        problem = [str(ticket.get(key) or "") for key in ("issueLevel1", "issueLevel2", "issueLevel3")]
        facts.append({
            "source_system": SOURCE_SYSTEM,
            "source_ticket_id": ticket_id,
            "source_item_id": source_item_id,
            "aftersales_business_key": stable_key(SOURCE_SYSTEM, ticket_id, source_item_id),
            "ticket_no": ticket.get("ticketNo"),
            "source_version": ticket.get("version"),
            "source_status": ticket.get("status"),
            "item_type": item.get("itemType") or ("ticket" if not items else "order"),
            # missing/wrong/extra are the actual affected merchandise rows for
            # warehouse discrepancy tickets.  They are issue facts just like
            # order rows; fulfillment-only reship/component rows stay out.
            "included_in_analytics": 1 if (not items or str(item.get("itemType") or "").lower() in ANALYTICS_ITEM_TYPES) else 0,
            "shop_id": ticket.get("shopId"),
            "shop_name": ticket.get("shopName"),
            "platform": ticket.get("platform"),
            "order_no": ticket.get("orderId"),
            "sub_order_no": item.get("subOrderNo"),
            "aftersale_id": ticket.get("aftersaleId"),
            "logistics_no": item.get("waybillNo") or ticket.get("waybillNo"),
            "problem1": problem[0],
            "problem2": problem[1],
            "problem3": problem[2],
            "problem_path": " > ".join(filter(None, problem)),
            "handle_method": ticket.get("handleMethod"),
            "amount": decimal_value(ticket.get("amount")),
            "refund_amount": decimal_value(item.get("refundAmount") if item else ticket.get("refundAmount")),
            "product_title": item.get("erpSpecName") or item.get("skuName"),
            "aftersales_product_id": item.get("goodsId"),
            "buy_qty": decimal_value(item.get("quantity")),
            "unit_price": decimal_value(item.get("unitPrice")),
            "sku_attr": item.get("skuProps"),
            "merchant_code": item.get("erpSpecNo"),
            "source_warehouse_code": item_warehouse or ticket_warehouse,
            "source_warehouse_name": ticket.get("wdtWarehouseName"),
            "source_logistics_company": item.get("logisticsCompany") or ticket.get("wdtLogisticsName"),
            "refund_apply_time": parse_datetime(item.get("refundApplyAt")),
            "paid_amount": decimal_value(ticket.get("actualPaidAmount")),
            "wdt_pay_time": parse_datetime(ticket.get("paidAt")),
            "api_created_at": created_at,
            "api_updated_at": updated_at,
            "api_synced_at": synced_at,
            "match_status": "matched" if item.get("erpSpecNo") else "pending",
            "matched_by": "ticket_api" if item.get("erpSpecNo") else "ticket_api_missing",
            "warehouse_match_status": "conflict" if warehouse_conflict else ("matched" if item_warehouse or ticket_warehouse else "pending"),
            "raw_payload": canonical_json({"ticket": ticket, "item": item}),
            "import_batch": batch_id,
        })
    return raw, facts


@dataclass(frozen=True)
class SegmentResult:
    tickets: dict[str, dict]
    pages: int


class SequentialFetcher:
    def __init__(self, delay: float):
        self.delay = delay
        self.last_started: float | None = None

    def open(self, request, **kwargs):
        now = time.monotonic()
        if self.last_started is not None:
            remaining = self.delay - (now - self.last_started)
            if remaining > 0:
                time.sleep(remaining)
        self.last_started = time.monotonic()
        return urllib.request.urlopen(request, **kwargs)

    def __call__(self, base_url: str, token: str, params: dict[str, Any]):
        return request_json(base_url, token, params, opener=self.open)


def confirm_ticket_absence(base_url, token, ticket_id, *, opener=urllib.request.urlopen):
    """Only the source's exact detail response can confirm an absent parent.

    The live API uses HTTP 400 / BAD_REQUEST / 工单不存在：<id>. Neither an
    empty list, generic 404, auth error, timeout nor another message is proof.
    Original records remain archived and the fact is only retired from reports.
    """
    if not str(ticket_id).isdigit():
        raise RuntimeError('source tickets disappeared without a valid identity')
    url=f"{base_url.rstrip('/')}/api/v1/tickets/{ticket_id}"
    request=urllib.request.Request(url,headers={'Authorization':f'Bearer {token}','Accept':'application/json'})
    try:
        with opener(request,timeout=30) as response:
            status=response.status;raw=response.read()
    except urllib.error.HTTPError as exc:
        status=exc.code;raw=exc.read()
    try:
        payload=json.loads(raw)
    except (ValueError,TypeError) as exc:
        raise RuntimeError('source ticket absence response is not valid JSON') from exc
    if not (status==400 and payload.get('success') is False and payload.get('code')=='BAD_REQUEST'
            and payload.get('message')==f'工单不存在：{ticket_id}'):
        raise RuntimeError(f'source tickets disappeared without authoritative absence proof: id={ticket_id}, HTTP={status}')
    return {'source_ticket_id':str(ticket_id),'url':url,'http_status':status,
            'observed_at':datetime.now(SHANGHAI).isoformat(),'response':payload,
            'response_sha256':hashlib.sha256(raw).hexdigest()}


def read_segment(base_url: str, token: str, start: datetime, end: datetime, page_size: int, delay: float, fetch=request_json) -> SegmentResult:
    tickets: dict[str, dict] = {}
    page_no = 1
    pages = 0
    inclusive_end = end - timedelta(seconds=1)
    while True:
        payload = fetch(base_url, token, {
            "createdAtStart": start.strftime("%Y-%m-%d %H:%M:%S"),
            "createdAtEnd": inclusive_end.strftime("%Y-%m-%d %H:%M:%S"),
            "pageNo": page_no,
            "pageSize": page_size,
        })
        rows = payload["data"]
        pages += 1
        if not rows:
            break
        for ticket in rows:
            ticket_id = "" if ticket.get("id") is None else str(ticket["id"]).strip()
            if not ticket_id or ticket_id in tickets:
                raise RuntimeError(f"duplicate or missing ticket identity on page {page_no}: {ticket_id or '<empty>'}")
            created_at = parse_datetime(ticket.get("createdAt"))
            if not created_at or not start <= created_at < end:
                raise RuntimeError(f"ticket {ticket_id} falls outside requested creation segment")
            tickets[ticket_id] = ticket
        page_no += 1
    return SegmentResult(tickets=tickets, pages=pages)


def segment_digest(result: SegmentResult) -> str:
    return hashlib.sha256(canonical_json(result.tickets).encode("utf-8")).hexdigest()


def segment_difference(first: SegmentResult, second: SegmentResult) -> dict[str, list[str]]:
    first_ids = set(first.tickets)
    second_ids = set(second.tickets)
    return {
        "added": sorted(second_ids - first_ids),
        "missing": sorted(first_ids - second_ids),
        "changed": sorted(
            ticket_id for ticket_id in first_ids & second_ids
            if canonical_json(first.tickets[ticket_id]) != canonical_json(second.tickets[ticket_id])
        ),
    }


def read_stable_history(base_url: str, token: str, start: datetime, end: datetime, page_size: int, delay: float, segment_days: int = 7, *, manifest=None, segment_budget_seconds=1800, progress=None, fetcher=None):
    history_started = time.monotonic()
    all_tickets: dict[str, dict] = {}
    pages = 0
    cursor = start
    fetch = fetcher or SequentialFetcher(delay)
    while cursor < end:
        segment_end = min(cursor + timedelta(days=segment_days), end)
        deadline = time.monotonic() + segment_budget_seconds
        first = read_segment(base_url, token, cursor, segment_end, page_size, delay, fetch=fetch)
        segment_pages = first.pages
        while True:
            second = read_segment(base_url, token, cursor, segment_end, page_size, delay, fetch=fetch)
            segment_pages += second.pages
            if segment_digest(first) == segment_digest(second):
                break
            if time.monotonic() >= deadline:
                difference = segment_difference(first, second)
                summary = {key: len(ids) for key, ids in difference.items()}
                raise RuntimeError(f"ticket segment changed within verification budget: {cursor} to {segment_end}; difference={canonical_json(summary)}")
            first = second
        overlap = set(all_tickets).intersection(first.tickets)
        if overlap:
            raise RuntimeError(f"ticket appeared in multiple creation segments: {sorted(overlap)[0]}")
        all_tickets.update(first.tickets)
        pages += segment_pages
        if manifest is not None:
            manifest.append((cursor, segment_end, len(second.tickets), segment_pages, segment_digest(second)))
        cursor = segment_end
        if progress:
            elapsed = max(time.monotonic() - history_started, 0.001)
            progress({"verified_through": str(cursor), "fixed_end": str(end),
                      "tickets_read": len(all_tickets), "pages_read": pages,
                      "elapsed_seconds": round(elapsed, 2),
                      "verified_tickets_per_minute": round(len(all_tickets) * 60 / elapsed, 2),
                      "remaining_creation_days": (end-cursor).total_seconds()/86400,
                      "remaining_pages": None})
    return all_tickets, pages


def rows_by_key(records: list[dict]) -> dict[str, dict]:
    result = {str(record["aftersales_business_key"]): record for record in records}
    if len(result) != len(records):
        raise RuntimeError("normalized fact rows contain duplicate business keys")
    return result


def existing_keys(conn, start: datetime, end: datetime) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT aftersales_business_key, raw_payload FROM ods_crm_aftersales
               WHERE source_system=%s AND api_created_at >= %s AND api_created_at < %s
                 AND COALESCE(match_status,'') <> 'source_removed'""",
            (SOURCE_SYSTEM, start, end),
        )
        return {str(key): str(payload or "") for key, payload in cur.fetchall()}


def source_is_enabled(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT analytics_enabled FROM dim_crm_source_state WHERE source_system=%s", (SOURCE_SYSTEM,))
        row = cur.fetchone()
    return bool(row and row[0])


def upsert_rows(conn, table: str, rows: list[dict], immutable: set[str]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    updates = ",".join(f"{column}=VALUES({column})" for column in columns if column not in immutable)
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(['%s'] * len(columns))}) ON DUPLICATE KEY UPDATE {updates}"
    with conn.cursor() as cur:
        cur.executemany(sql, [[row.get(column) for column in columns] for row in rows])


def sync(conn, base_url: str, token: str, start: datetime, end: datetime, batch_id: str, page_size: int, delay: float, dry_run: bool, progress=None, detail_token=None) -> dict[str, Any]:
    started = time.monotonic()
    manifest = []
    fetcher=SequentialFetcher(delay)
    tickets, pages = read_stable_history(base_url, token, start, end, page_size, delay, manifest=manifest, progress=progress,fetcher=fetcher)
    synced_at = datetime.now()
    raw_rows: list[dict] = []
    fact_rows: list[dict] = []
    for ticket in tickets.values():
        raw, facts = normalize_ticket(ticket, batch_id, synced_at)
        raw_rows.append(raw)
        fact_rows.extend(facts)
    incoming = rows_by_key(fact_rows)
    existing = existing_keys(conn, start, end)
    missing = sorted(set(existing) - set(incoming))
    changed = sum(key in existing and existing[key] != str(record["raw_payload"]) for key, record in incoming.items())
    stats = {
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "verified_segments": len(manifest),
        "segment_digests": [entry[-1] for entry in manifest],
        "pages_read": pages,
        "tickets_read": len(tickets),
        "fact_rows": len(fact_rows),
        "new_rows": sum(key not in existing for key in incoming),
        "changed_rows": changed,
        "missing_rows": len(missing),
        "missing_sample": missing[:20],
    }
    # A complete new ticket payload proves removal of a child. Missing parents
    # require a separate, authenticated detail lookup for every parent ID.
    absent_parents=set();removed_children=[]
    for key in missing:
        try:
            parent = str(json.loads(existing[key]).get("ticket", {}).get("id", ""))
        except (ValueError, TypeError):
            parent = ""
        if not parent:
            raise RuntimeError('source tickets disappeared without parent identity evidence')
        if parent not in tickets:
            absent_parents.add(parent)
        else:
            removed_children.append(key)
    # Export has a separate service credential; the normal authenticated detail
    # API requires the source viewer credential. They are not interchangeable.
    if absent_parents and not detail_token:
        raise RuntimeError('source tickets disappeared; source detail credential required for authoritative verification')
    absence_proofs=[confirm_ticket_absence(base_url,detail_token,parent,opener=fetcher.open) for parent in sorted(absent_parents)]
    stats['confirmed_absent_tickets']=len(absence_proofs)
    stats['absence_proofs']=absence_proofs
    stats['removed_child_rows']=len(removed_children)
    stats['elapsed_seconds']=round(time.monotonic()-started,2)
    if dry_run:
        return stats
    with conn.cursor() as cur:
        cur.execute("""INSERT IGNORE INTO crm_ticket_version
            (source_system,source_ticket_id,content_hash,observed_at,import_batch,raw_payload)
            SELECT source_system,source_ticket_id,content_hash,synced_at,import_batch,raw_payload
            FROM ods_crm_ticket_raw WHERE source_system=%s
              AND source_created_at >= %s AND source_created_at < %s""", (SOURCE_SYSTEM,start,end))
        cur.executemany("""INSERT IGNORE INTO crm_ticket_version
            (source_system,source_ticket_id,content_hash,observed_at,import_batch,raw_payload)
            VALUES (%s,%s,%s,%s,%s,%s)""", [
                (SOURCE_SYSTEM,r['source_ticket_id'],r['content_hash'],synced_at,batch_id,r['raw_payload']) for r in raw_rows])
        if removed_children:
            # Preserve the old fact and its original payload for record-level
            # audit. A later authoritative reappearance reactivates it through
            # the normal upsert, using the same immutable source item identity.
            cur.executemany("""UPDATE ods_crm_aftersales SET included_in_analytics=0,
                match_status='source_removed',matched_by='source_complete_item_set'
                WHERE source_system=%s AND aftersales_business_key=%s""",
                            [(SOURCE_SYSTEM,key) for key in removed_children])
        for proof in absence_proofs:
            cur.execute("""INSERT INTO crm_ticket_absence_evidence
                (batch_id,source_system,source_ticket_id,observed_at,evidence_json)
                VALUES(%s,%s,%s,%s,%s)""",(batch_id,SOURCE_SYSTEM,proof['source_ticket_id'],synced_at,canonical_json(proof)))
            cur.execute("""UPDATE ods_crm_aftersales SET included_in_analytics=0,
                match_status='source_removed',matched_by='source_detail_absence'
                WHERE source_system=%s AND source_ticket_id=%s""",(SOURCE_SYSTEM,proof['source_ticket_id']))
        cur.executemany("""INSERT INTO crm_ticket_read_segment
            (batch_id,segment_start,segment_end,tickets_read,pages_read,content_digest)
            VALUES (%s,%s,%s,%s,%s,%s)""", [(batch_id,*entry) for entry in manifest])
    upsert_rows(conn, "ods_crm_ticket_raw", raw_rows, {"source_system", "source_ticket_id"})
    upsert_rows(conn, "ods_crm_aftersales", fact_rows, {"id", "aftersales_business_key", "source_system", "source_ticket_id", "source_item_id"})
    return stats


def require_date(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), datetime_time.min)


def main() -> int:
    parser = argparse.ArgumentParser(description="同步售后工单 JSON 到统一售后事实表")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", help="左闭右开的结束日期，默认今天零点")
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--delay", type=float, default=7.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.page_size <= 200:
        raise SystemExit("page-size 必须在 1 到 200 之间")
    if args.delay < 7:
        raise SystemExit("delay 不能小于 7 秒")
    start = require_date(args.start_date)
    end = require_date(args.end_date) if args.end_date else datetime.combine(datetime.now(SHANGHAI).date(), datetime_time.min)
    if start >= end:
        raise SystemExit("start-date 必须早于 end-date")
    token = os.environ.get("TICKET_EXPORT_API_JWT", "").strip()
    if not token:
        raise SystemExit("缺少 TICKET_EXPORT_API_JWT")
    base_url = os.environ.get("TICKET_EXPORT_BASE_URL", DEFAULT_BASE_URL)
    batch_id = f"ticket_{datetime.now():%Y%m%d_%H%M%S}"
    conn = connect_mysql()
    started_at = datetime.now()
    stats: dict[str, Any] = {}
    try:
        if not args.dry_run:
            from crm_report_schema import ensure_report_schema
            ensure_report_schema(conn)
        reconciliation_status = "approved" if source_is_enabled(conn) else "pending"
        stats = sync(conn, base_url, token, start, end, batch_id, args.page_size, args.delay, args.dry_run,
                     detail_token=os.environ.get('TICKET_DETAIL_API_JWT'),
                     progress=lambda value: print(canonical_json(value), flush=True))
        if args.dry_run:
            conn.rollback()
        else:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO etl_crm_ticket_batches
                       (batch_id, source_system, coverage_start, coverage_end, status, reconciliation_status,
                        pages_read, tickets_read, fact_rows, new_rows, changed_rows, missing_rows, started_at, completed_at)
                       VALUES (%s,%s,%s,%s,'published',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (batch_id, SOURCE_SYSTEM, start, end, reconciliation_status, stats["pages_read"], stats["tickets_read"], stats["fact_rows"],
                     stats["new_rows"], stats["changed_rows"], stats["missing_rows"], started_at, datetime.now()),
                )
            conn.commit()
    except Exception as exc:
        conn.rollback()
        if not args.dry_run:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO etl_crm_ticket_batches
                           (batch_id, source_system, coverage_start, coverage_end, status, reconciliation_status,
                            pages_read, tickets_read, fact_rows, new_rows, changed_rows, missing_rows,
                            error_summary, started_at, completed_at)
                           VALUES (%s,%s,%s,%s,'failed','pending',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (batch_id, SOURCE_SYSTEM, start, end, stats.get("pages_read", 0), stats.get("tickets_read", 0),
                         stats.get("fact_rows", 0), stats.get("new_rows", 0), stats.get("changed_rows", 0),
                         stats.get("missing_rows", 0), str(exc)[:1000], started_at, datetime.now()),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
        raise
    finally:
        conn.close()
    print(canonical_json({"batch_id": batch_id, "coverage_start": str(start), "coverage_end": str(end), "dry_run": args.dry_run, **stats}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
