import json,sys,unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import crm_original_order_read as reader


class OriginalReadTests(unittest.TestCase):
    def test_failure_rolls_back_partial_proofs_and_records_failed_batch(self):
        conn=MagicMock();events=[]
        conn.commit.side_effect=lambda:events.append('commit')
        conn.rollback.side_effect=lambda:events.append('rollback')
        with patch.object(reader,'query',return_value=[{'batch_id':'source','status':'published','reconciliation_status':'approved'}]), \
             patch.object(reader,'read_proofs',side_effect=TimeoutError('source timeout')):
            with self.assertRaises(TimeoutError):
                reader.collect_batch(conn,None,date(2026,9,16),Path('/unused'),reader.PLATFORMS)
        self.assertEqual(events,['commit','rollback','commit'])
        statements=[call.args[0] for call in conn.cursor.return_value.__enter__.return_value.execute.call_args_list]
        self.assertIn("status='failed'",statements[-1])
        self.assertFalse(any("status='complete'" in sql for sql in statements))

    def test_later_failed_or_partial_read_cannot_use_previous_proofs(self):
        for status in ['running','failed']:
            with patch.object(reader,'query',return_value=[{'status':status}]):
                with self.assertRaisesRegex(ValueError,'incomplete or failed'):
                    reader.require_complete_read(None,date(2026,9,16),'source')

    def test_scope_source_and_platform_subset_must_match(self):
        row={'status':'complete','scope_end':date(2026,9,16),'source_batch_id':'source','batch_id':'read',
             'summary_json':json.dumps({'platforms':sorted(reader.PLATFORMS),'requested':0,'proofs':[]})}
        with patch.object(reader,'query',return_value=[row]):
            self.assertEqual(reader.require_complete_read(None,date(2026,9,16),'source'),'read')
            for end,source in [(date(2026,9,17),'source'),(date(2026,9,16),'new-source')]:
                with self.assertRaisesRegex(ValueError,'source and scope'):reader.require_complete_read(None,end,source)
        row['summary_json']=json.dumps({'platforms':['jd'],'requested':0,'proofs':[]})
        with patch.object(reader,'query',return_value=[row]):
            with self.assertRaisesRegex(ValueError,'source and scope'):reader.require_complete_read(None,date(2026,9,16),'source')
