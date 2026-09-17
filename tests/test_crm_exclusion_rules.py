import json
import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

from scripts import crm_exclusion_rules_refresh as rules


class ExclusionRuleTests(unittest.TestCase):
    def test_default_rules_are_the_confirmed_six_entries(self):
        loaded = rules.load_defaults()
        self.assertEqual(len(loaded), 6)
        self.assertIn(
            {"p1": "快递问题", "p2": "顾客退款", "p3": "*", "note": "顾客退款不进入经营异常统计"},
            loaded,
        )
        self.assertIn(
            {"p1": "快递问题", "p2": "物流延迟", "p3": "需催件", "note": "仅催件路径可剔除"},
            loaded,
        )
        self.assertIn(
            {"p1": "买家问题", "p2": "无理由退", "p3": "*", "note": "无理由退不进入经营异常统计"},
            loaded,
        )

    def test_rule_file_contains_no_old_risk_taxonomy(self):
        text = json.dumps(rules.load_defaults(), ensure_ascii=False)
        for obsolete in ("零容忍", "规模型", "比率型", "观察项", "剔除项", "待分类"):
            self.assertNotIn(obsolete, text)


if __name__ == "__main__":
    unittest.main()
