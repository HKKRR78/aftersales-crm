import hashlib,json,tempfile,unittest,sys
from pathlib import Path
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from crm_original_order_proof import original_from_evidence,reconcile_original_order
from crm_report_model import canonical

class OriginalProofTests(unittest.TestCase):
    def example(self):
        sale=dict(platform='wechat_shop',line_key='line',order_no='order',native_sku_id='sku',
                  product_id='goods',code='A*3+B*6',quantity=Decimal(2),sub_keys={'order'},evidence={})
        original=dict(tid='order',order_count=1,goods_list=[dict(tid='order',oid='order_001',
                      goods_id='goods',spec_id='sku',spec_no='A*3+B*6',num='2',rec_id='real-record')])
        return sale,original
    def test_complete_original_item_set_proves_alias_and_parent(self):
        sale,original=self.example()
        self.assertTrue(reconcile_original_order([sale],original,{'content_hash':'hash'}))
        self.assertIn('order_001',sale['sub_keys']);self.assertTrue(sale['original_order_complete'])
    def test_partial_or_different_pack_never_proves_parent(self):
        sale,original=self.example();original['order_count']=2
        self.assertFalse(reconcile_original_order([sale],original,{}))
        original['order_count']=1;original['goods_list'][0]['spec_no']='A'
        self.assertFalse(reconcile_original_order([sale],original,{}))
        self.assertNotIn('original_order_complete',sale)
    def test_extra_native_line_or_quantity_conflict_fails(self):
        sale,original=self.example()
        self.assertFalse(reconcile_original_order([sale,{**sale,'line_key':'different'}],original,{}))
        original['goods_list'][0]['num']='6'
        self.assertFalse(reconcile_original_order([sale],original,{}))

    def test_modified_api_artifact_or_database_payload_cannot_certify_order(self):
        _,original=self.example()
        envelope=dict(endpoint='vip_api_trade_query.php',request={'tid':'order'},
                      response=dict(code=0,total_count=1,trade_list=[original]))
        with tempfile.TemporaryDirectory() as directory:
            raw=canonical(envelope).encode()
            path=Path(directory)/(hashlib.sha256(raw).hexdigest()+'.json')
            path.write_bytes(raw)
            row=dict(artifact_path=str(path),endpoint=envelope['endpoint'],order_no='order',
                     original_order_json=canonical(original),content_hash=hashlib.sha256(canonical(original).encode()).hexdigest())
            self.assertEqual(original_from_evidence(row),original)
            row['original_order_json']=json.dumps({**original,'order_count':2})
            with self.assertRaisesRegex(ValueError,'content changed'):original_from_evidence(row)
            path.write_bytes(raw+b' ')
            with self.assertRaisesRegex(ValueError,'artifact hash changed'):original_from_evidence(row)

    def test_exact_empty_response_is_preserved_without_inventing_an_order(self):
        envelope=dict(endpoint='vip_api_trade_query.php',request={'tid':'order'},response=dict(code=0,total_count=0,trade_list=[]))
        with tempfile.TemporaryDirectory() as directory:
            raw=canonical(envelope).encode();path=Path(directory)/(hashlib.sha256(raw).hexdigest()+'.json');path.write_bytes(raw)
            row=dict(artifact_path=str(path),endpoint=envelope['endpoint'],order_no='order',original_order_json='null',
                     content_hash=hashlib.sha256(b'null').hexdigest())
            self.assertIsNone(original_from_evidence(row))
