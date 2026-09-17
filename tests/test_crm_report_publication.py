import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.modules.setdefault('pymysql', types.ModuleType('pymysql'))
import crm_report_publish as publisher
from crm_report_build import unapproved_denominator_rows


class PublicationTests(unittest.TestCase):
    def test_verified_attribution_requires_original_platform_line(self):
        valid={'platform':'pinduoduo','shop_key':'shop','merchant_code':'A*5','match_status':'verified',
               'evidence_json':json.dumps({'sales':[{'table':'vw_pdd_order_ready','row_key':'line'}]})}
        publisher.verify_attribution_evidence([valid])
        invalid={**valid,'evidence_json':json.dumps({'sales':[{'table':'catalog','issue_mapping_only':True}]})}
        with self.assertRaisesRegex(ValueError,'candidate-only'):
            publisher.verify_attribution_evidence([invalid])

    def test_issue_only_batch_marks_every_required_denominator_unknown(self):
        scope={'requiredPeriods':[{'start':'2026-09-06','end':'2026-09-13','kind':'complete'},
                                  {'start':'2026-09-06','end':'2026-09-13','kind':'comparison'}]}
        rows=unapproved_denominator_rows('batch',scope)
        self.assertEqual(len(rows),5)
        self.assertEqual({row[3] for row in rows},{'total','merchant_code','sales_link','warehouse','warehouse_sales_link'})
        self.assertTrue(all(row[5]==0 and row[6]=='sales_coverage_not_approved' for row in rows))

    def test_stale_compare_and_swap_never_writes_pointer(self):
        conn = MagicMock()
        with patch.object(publisher, 'query', return_value=[{'batch_id': 'newer'}]):
            with self.assertRaisesRegex(ValueError, 'current report changed'):
                publisher.select_batch(conn, 'candidate', 'old')
        conn.cursor.assert_not_called()

    def test_source_or_rule_change_after_verification_blocks_selection(self):
        conn = MagicMock()
        responses = [[{'batch_id': 'old'}], [{'status': 'verified', 'summary_json': json.dumps({'evidenceSha256': 'digest'})}]]
        with patch.object(publisher, 'query', side_effect=responses), \
             patch.object(publisher, 'validate', side_effect=ValueError('source changed')):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                publisher.select_batch(conn, 'candidate', 'old')
        conn.cursor.assert_not_called()

    def test_tampered_evidence_cannot_be_published(self):
        conn = MagicMock()
        responses = [[{'batch_id': 'old'}], [{'status': 'verified', 'summary_json': json.dumps({'evidenceSha256': 'original'})}]]
        with patch.object(publisher, 'query', side_effect=responses), \
             patch.object(publisher, 'validate', return_value=('changed',0)):
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                publisher.select_batch(conn, 'candidate', 'old')
        conn.cursor.assert_not_called()

    def test_full_publication_rejects_coverage_gaps(self):
        with self.assertRaisesRegex(ValueError,'paid-window coverage remains incomplete'):
            publisher.coverage_policy({'n':10,'days':2,'gaps':1},2,publisher.FULL)

    def test_partial_publication_requires_complete_matrix_but_allows_honest_gaps(self):
        self.assertEqual(publisher.coverage_policy({'n':10,'days':2,'gaps':7},2,publisher.PARTIAL),7)
        with self.assertRaisesRegex(ValueError,'coverage matrix is incomplete'):
            publisher.coverage_policy({'n':10,'days':1,'gaps':7},2,publisher.PARTIAL)

    def test_partial_publication_allows_no_continuous_sales_watermark(self):
        publisher.snapshot_policy({'rules':[], 'completeThrough':''},publisher.PARTIAL)
        with self.assertRaisesRegex(ValueError,'continuous coverage'):
            publisher.snapshot_policy({'rules':[], 'completeThrough':''},publisher.FULL)

    def test_selection_revalidates_the_stored_partial_kind(self):
        conn=MagicMock()
        summary={'evidenceSha256':'digest','verificationKind':publisher.PARTIAL}
        responses=[[{'batch_id':'old'}],[{'status':'verified','summary_json':json.dumps(summary)}]]
        with patch.object(publisher,'query',side_effect=responses),patch.object(publisher,'validate',return_value=('digest',7)) as validate:
            publisher.select_batch(conn,'candidate','old')
        validate.assert_called_once_with(conn,'candidate',publisher.PARTIAL)


if __name__ == '__main__':
    unittest.main()
