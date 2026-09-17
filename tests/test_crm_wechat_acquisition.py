import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from crm_read_wechat_originals import response_cache

class AcquisitionResumeTests(unittest.TestCase):
    def row(self,order='1',observed='2026-09-16T18:00:00+08:00'):
        return dict(endpoint='/channels/ec/order/get',request={'order_id':'1'},observed_at=observed,response={'order':{'order_id':order}})
    def test_retains_last_real_response_and_identifies_unfinished_tail(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'responses.jsonl';r=self.row()
            p.write_text(json.dumps(r)+'\n'+json.dumps(self.row(observed='2026-09-16T18:05:00+08:00'))+'\n{"endpoint":')
            before=p.read_bytes();cache,evidence=response_cache([p])
            self.assertEqual(next(iter(cache.values()))['observed_at'],'2026-09-16T18:05:00+08:00')
            self.assertTrue(evidence[0]['unfinished_last_record']);self.assertEqual(p.read_bytes(),before)
    def test_conflicting_identity_and_broken_complete_record_are_not_reused(self):
        for raw in [json.dumps(self.row(order='different'))+'\n','broken\n'+json.dumps(self.row())+'\n']:
            with self.subTest(raw=raw),tempfile.TemporaryDirectory() as d:
                p=Path(d)/'responses.jsonl';p.write_text(raw)
                with self.assertRaises(ValueError):response_cache([p])

if __name__=='__main__':unittest.main()
