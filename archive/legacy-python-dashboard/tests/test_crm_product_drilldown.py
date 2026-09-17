import unittest
from urllib.parse import parse_qs, urlparse

import crm_server


def issue_row(code: str, name: str, issues: int, total5: int) -> dict:
    return {
        "code": code,
        "name": name,
        "p1": "产品问题",
        "p2": "包装破损",
        "p3": "",
        "category": "产品问题",
        "latestIssues": issues,
        "total5": total5,
        "latestRate": 1.0,
        "latestWow": 0.0,
        "weeks": [
            {"issues": total5 - issues, "orders": 100, "rate": 1.0, "wow": None, "wowText": ""},
            {"issues": issues, "orders": 100, "rate": 1.0, "wow": 0.0, "wowText": "0.00%"},
        ],
    }


class ProductDrilldownTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            issue_row("SKU*5", "同款商品200g", 4, 7),
            issue_row("SKU*5", "同款商品旧标题", 3, 5),
            issue_row("OTHER", "同款商品200g", 2, 3),
        ]

    def test_merchant_code_filter_is_exact_and_reconciles_to_product_total(self):
        products = crm_server.aggregate_products(self.rows, ["上周", "本周"])
        product = next(row for row in products if row["code"] == "SKU*5")
        details = crm_server.filtered_rows(self.rows, {"merchant_code": ["SKU*5"]})
        self.assertEqual(sum(row["latestIssues"] for row in details), product["latestIssues"])
        self.assertEqual(sum(row["total5"] for row in details), product["total5"])
        self.assertEqual({row["code"] for row in details}, {"SKU*5"})
        self.assertEqual(crm_server.filtered_rows(self.rows, {"merchant_code": ["SKU"]}), [])

    def test_product_detail_url_uses_exact_code_and_period(self):
        url = crm_server.product_detail_url("SKU*5", "progress")
        parsed = urlparse(url)
        self.assertEqual(parsed.path, "/crm/dashboard/detail")
        self.assertEqual(parse_qs(parsed.query), {"merchant_code": ["SKU*5"], "period": ["progress"]})
        self.assertEqual(crm_server.product_detail_url("未填"), "")

    def test_product_cells_render_exact_drilldown_links(self):
        row = dict(self.rows[0], _detailUrl=crm_server.product_detail_url("SKU*5"))
        rendered_code = crm_server.display_value(row, "code")
        rendered_name = crm_server.display_value(row, "name")
        self.assertIn("merchant_code=SKU%2A5", rendered_code)
        self.assertIn("按商家编码精确查看售后明细", rendered_code)
        self.assertIn("merchant_code=SKU%2A5", rendered_name)

    def test_exact_code_is_preserved_in_form_tabs_and_export(self):
        query = {"merchant_code": ["SKU*5"], "period": ["progress"]}
        form = crm_server.filter_form("/crm/dashboard/detail", query, {})
        tabs = crm_server.period_tabs("/crm/dashboard/detail", query)
        link = crm_server.excel_export_link("detail", {"username": "viewer", "role": "viewer"}, query)
        self.assertIn('name="merchant_code" value="SKU*5"', form)
        self.assertIn("merchant_code=SKU%2A5", tabs)
        self.assertIn("merchant_code=SKU%2A5", link)


if __name__ == "__main__":
    unittest.main()
