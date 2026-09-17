import hashlib
import io
import json
import sys
import types
import unittest
import urllib.error
from datetime import datetime
from unittest.mock import patch

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

from scripts import crm_ticket_sync as sync


def ticket(ticket_id="8083", items=None, **overrides):
    value = {
        "id": ticket_id,
        "ticketNo": f"WO-{ticket_id}",
        "shopName": "抖音-测试店",
        "orderId": "6955714619987859355",
        "issueLevel1": "快递问题",
        "issueLevel2": "顾客退款",
        "createdAt": "2026-09-09T09:10:55",
        "updatedAt": "2026-09-10T10:57:38",
        "paidAt": "2026-09-05T23:56:44",
        "skuItems": [{
            "id": 8173,
            "subOrderNo": "SUB-1",
            "erpSpecNo": "2025080301",
            "goodsId": "3788833637621956988",
            "warehouseCode": "lzgz",
            "itemType": "order",
            "quantity": 1,
            "unitPrice": "19.9000",
        }] if items is None else items,
    }
    value.update(overrides)
    return value


class TicketNormalizationTests(unittest.TestCase):
    def test_preserves_long_identifiers_and_independent_suborder(self):
        long_id = "9" * 70
        row = ticket(ticket_id=long_id)
        raw, facts = sync.normalize_ticket(row, "batch", datetime(2026, 9, 14, 8))
        self.assertEqual(raw["source_ticket_id"], long_id)
        self.assertEqual(facts[0]["sub_order_no"], "SUB-1")
        self.assertEqual(facts[0]["aftersales_product_id"], "3788833637621956988")
        self.assertEqual(facts[0]["aftersales_business_key"], hashlib.sha256(f"ticket_service:{long_id}:8173".encode()).hexdigest())

    def test_empty_ticket_creates_one_analytics_placeholder(self):
        _raw, facts = sync.normalize_ticket(ticket(items=[]), "batch", datetime.now())
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["source_item_id"], "__ticket__")
        self.assertEqual(facts[0]["included_in_analytics"], 1)

    def test_fulfillment_only_items_are_retained_but_excluded(self):
        _raw, facts = sync.normalize_ticket(ticket(items=[{"id": 1, "itemType": "reship"}]), "batch", datetime.now())
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["item_type"], "reship")
        self.assertEqual(facts[0]["included_in_analytics"], 0)

    def test_warehouse_discrepancy_items_are_independent_issue_facts(self):
        for item_type in ("missing", "wrong", "extra"):
            with self.subTest(item_type=item_type):
                _raw, facts = sync.normalize_ticket(ticket(items=[{"id": 1, "itemType": item_type}]), "batch", datetime.now())
                self.assertEqual(facts[0]["included_in_analytics"], 1)

    def test_missing_third_issue_is_preserved_as_empty(self):
        _raw, facts = sync.normalize_ticket(ticket(), "batch", datetime.now())
        self.assertEqual(facts[0]["problem3"], "")

    def test_item_warehouse_wins_and_conflict_is_visible(self):
        _raw, facts = sync.normalize_ticket(ticket(wdtWarehouseNo="other"), "batch", datetime.now())
        self.assertEqual(facts[0]["source_warehouse_code"], "lzgz")
        self.assertEqual(facts[0]["warehouse_match_status"], "conflict")


class TicketPaginationTests(unittest.TestCase):
    def test_only_exact_authoritative_missing_response_confirms_absence(self):
        response={'success':False,'code':'BAD_REQUEST','message':'工单不存在：11099','traceId':'test'}
        error=urllib.error.HTTPError('https://example.test/api/v1/tickets/11099',400,'missing',{},io.BytesIO(json.dumps(response).encode()))
        result=sync.confirm_ticket_absence('https://example.test','test-token','11099',opener=unittest.mock.Mock(side_effect=error))
        self.assertEqual(result['source_ticket_id'],'11099')
        self.assertEqual(result['http_status'],400)
        self.assertEqual(len(result['response_sha256']),64)

    def test_auth_error_and_generic_not_found_do_not_confirm_absence(self):
        for status,body in [(401,{'success':False,'message':'Token 无效或已过期'}),
                            (404,{'success':False,'message':'not found'}),
                            (400,{'success':False,'code':'BAD_REQUEST','message':'工单不存在：another-id'})]:
            error=urllib.error.HTTPError('https://example.test',status,'failure',{},io.BytesIO(json.dumps(body).encode()))
            with self.subTest(status=status),self.assertRaisesRegex(RuntimeError,'without authoritative'):
                sync.confirm_ticket_absence('https://example.test','test-token','11099',opener=unittest.mock.Mock(side_effect=error))

    def test_reads_until_empty_page_and_rejects_duplicate_ids(self):
        payloads = [
            {"success": True, "code": "0", "data": [ticket("1"), ticket("2")]},
            {"success": True, "code": "0", "data": [ticket("2")]},
        ]
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            sync.read_segment("https://example.test", "secret", datetime(2026, 9, 9), datetime(2026, 9, 10), 2, 0, fetch=lambda *_args: payloads.pop(0))

    def test_partial_page_does_not_end_pagination(self):
        payloads = [
            {"success": True, "code": "0", "data": [ticket("1")]},
            {"success": True, "code": "0", "data": [ticket("2")]},
            {"success": True, "code": "0", "data": []},
        ]
        result = sync.read_segment(
            "https://example.test", "secret",
            datetime(2026, 9, 9), datetime(2026, 9, 10), 20, 0,
            fetch=lambda *_args: payloads.pop(0),
        )
        self.assertEqual(set(result.tickets), {"1", "2"})
        self.assertEqual(result.pages, 3)

    def test_stable_history_rejects_changed_second_read(self):
        first = sync.SegmentResult({"1": ticket("1")}, 1)
        second = sync.SegmentResult({"1": ticket("1", status="DONE")}, 1)
        with patch.object(sync, "read_segment", side_effect=[first, second]):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                sync.read_stable_history("url", "token", datetime(2026, 9, 9), datetime(2026, 9, 10), 20, 0, segment_budget_seconds=0)

    def test_changed_segment_is_read_again_until_two_adjacent_snapshots_agree(self):
        first = sync.SegmentResult({"1": ticket("1")}, 2)
        second = sync.SegmentResult({"1": ticket("1", status="DONE")}, 2)
        manifest = []
        with patch.object(sync, "read_segment", side_effect=[first, second, second]):
            rows, pages = sync.read_stable_history("url", "token", datetime(2026, 9, 9), datetime(2026, 9, 10), 200, 0, manifest=manifest)
        self.assertEqual(rows['1']['status'], 'DONE')
        self.assertEqual(pages, 6)
        self.assertEqual(manifest[0][2:4], (1, 6))

    def test_segment_difference_reports_added_missing_and_changed(self):
        first = sync.SegmentResult({"1": ticket("1"), "2": ticket("2")}, 1)
        second = sync.SegmentResult({"2": ticket("2", status="DONE"), "3": ticket("3")}, 1)
        self.assertEqual(sync.segment_difference(first, second), {
            "added": ["3"], "missing": ["1"], "changed": ["2"],
        })

    def test_auth_error_is_not_retried(self):
        error = urllib.error.HTTPError("url", 401, "unauthorized", {}, io.BytesIO(b""))
        opener = unittest.mock.Mock(side_effect=error)
        with self.assertRaisesRegex(RuntimeError, "401"):
            sync.request_json("https://example.test", "secret", {}, opener=opener, sleep=lambda _seconds: None)
        self.assertEqual(opener.call_count, 1)

    def test_429_uses_retry_after_and_then_succeeds(self):
        error = urllib.error.HTTPError("url", 429, "limited", {"Retry-After": "9"}, io.BytesIO(b""))
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.StringIO(json.dumps({"success": True, "code": "0", "data": []}))
        sleep = unittest.mock.Mock()
        payload = sync.request_json("https://example.test", "secret", {}, opener=unittest.mock.Mock(side_effect=[error, response]), sleep=sleep)
        self.assertEqual(payload["data"], [])
        sleep.assert_called_once_with(9.0)

    def test_missing_existing_fact_blocks_write(self):
        normalized = sync.normalize_ticket(ticket("1"), "batch", datetime.now())
        with patch.object(sync, "read_stable_history", return_value=({"1": ticket("1")}, 2)), \
             patch.object(sync, "existing_keys", return_value={"missing-key": "payload"}), \
             patch.object(sync, "upsert_rows") as upsert:
            with self.assertRaisesRegex(RuntimeError, "disappeared"):
                sync.sync(object(), "url", "token", datetime(2026, 9, 9), datetime(2026, 9, 10), "batch", 20, 0, False)
        upsert.assert_not_called()
        self.assertTrue(normalized[1])

    def test_removed_child_is_retired_with_raw_fact_retained(self):
        old = ticket("1", items=[{"id": 1, "itemType": "order"}, {"id": 2, "itemType": "order"}])
        new = ticket("1", items=[{"id": 2, "itemType": "order"}])
        _, old_facts = sync.normalize_ticket(old, "old", datetime.now())
        existing = {row['aftersales_business_key']: row['raw_payload'] for row in old_facts}
        conn = unittest.mock.MagicMock()
        with patch.object(sync, "read_stable_history", return_value=({"1": new}, 2)), \
             patch.object(sync, "existing_keys", return_value=existing), \
             patch.object(sync, "upsert_rows"):
            result = sync.sync(conn, "url", "token", datetime(2026, 9, 9), datetime(2026, 9, 10), "batch", 200, 0, False)
        calls = conn.cursor.return_value.__enter__.return_value.executemany.call_args_list
        statements = [call.args[0] for call in calls]
        self.assertEqual(result['removed_child_rows'], 1)
        self.assertFalse(any('DELETE' in sql for sql in statements))
        retirement = [call for call in calls if 'source_complete_item_set' in call.args[0]]
        self.assertEqual(retirement[0].args[1], [(sync.SOURCE_SYSTEM, old_facts[0]['aftersales_business_key'])])


if __name__ == "__main__":
    unittest.main()
