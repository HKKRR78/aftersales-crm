import sys
import types
import unittest
from datetime import date,datetime
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.modules.setdefault('pymysql',types.ModuleType('pymysql'))
import crm_report_publish as publish
from crm_report_model import source_fact_key
from crm_report_integrity import record_sets,require_record_sets,TABLE_KEYS
from unittest.mock import MagicMock


class IssueSetTests(unittest.TestCase):
    def setUp(self):
        self.fact=dict(source_system='ticket_service',source_ticket_id='real-test-ticket',source_item_id='item',
            id=10,api_created_at=datetime(2026,9,9),problem1='产品问题',problem2='破损',problem3='',merchant_code='base')
        key=source_fact_key(self.fact)
        self.fact.update(_canonical_issue_key=key,_source_inputs=[dict(input_key=key,source_system='ticket_service',
            source_ticket_id='real-test-ticket',source_item_id='item',source_fact_id=10)])
        self.row=dict(issue_key=key,source_fact_id=10,
            created_at=self.fact['api_created_at'],problem1='产品问题',problem2='破损',problem3='',raw_code='base',merchant_code='base*3')
        self.lineage=dict(input_key=key,canonical_issue_key=key,source_system='ticket_service',
            source_ticket_id='real-test-ticket',source_item_id='item')

    def check(self,rows,rules=None):
        with patch.object(publish,'current_facts',return_value=([self.fact],[])),patch.object(publish,'query',side_effect=[rows,[self.lineage]]):
            return publish.verify_current_issue_set(object(),'batch',date(2026,8,9),date(2026,9,16),rules or [])

    def test_missing_or_residual_item_is_not_hidden_by_balanced_totals(self):
        for rows in [[],[self.row,{**self.row,'issue_key':'removed-child'}]]:
            with self.assertRaisesRegex(ValueError,'authoritative source items'):self.check(rows)

    def test_changed_source_occurrence_or_classification_blocks_old_snapshot(self):
        for change in [dict(created_at=datetime(2026,9,1)),dict(problem1='买家问题'),dict(raw_code='made-up')]:
            with self.assertRaisesRegex(ValueError,'source fields changed'):self.check([{**self.row,**change}])

    def test_rule_only_report_recounts_current_rules_without_changing_source_facts(self):
        totals,conservation=self.check([self.row])
        self.assertEqual(totals,dict(operating=1,matchedOperating=1,unmatchedOperating=0))
        self.assertEqual(conservation,dict(sourceInputs=1,canonicalIssues=1,mergedDuplicates=0,bySource={'ticket_service':1}))
        rules=[dict(enabled=True,p1='产品问题',p2='破损',p3='*')]
        self.assertEqual(self.check([self.row],rules)[0],dict(operating=0,matchedOperating=0,unmatchedOperating=0))
        self.assertEqual(self.row['merchant_code'],'base*3')


class RecordBindingTests(unittest.TestCase):
    def connection(self, sales=3, complete=1):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        cur.description=[('batch_id',),('value',)]
        chunks=[]
        for value in [1,1,sales,1,complete,1]:chunks.extend([[('batch',value)],[]])
        cur.fetchmany.side_effect=chunks
        return conn

    def test_changed_quantity_with_unchanged_row_count_blocks_publication(self):
        before=record_sets(self.connection(),'batch')
        with self.assertRaisesRegex(ValueError,'denominators or coverage changed'):
            require_record_sets(self.connection(sales=30),'batch',before)

    def test_changed_completeness_or_missing_binding_cannot_authorize_zero(self):
        before=record_sets(self.connection(),'batch')
        with self.assertRaisesRegex(ValueError,'coverage changed'):
            require_record_sets(self.connection(complete=0),'batch',before)
        with self.assertRaisesRegex(ValueError,'coverage changed'):
            require_record_sets(self.connection(),'batch',None)
        self.assertEqual(set(before),set(TABLE_KEYS))


if __name__=='__main__':unittest.main()
