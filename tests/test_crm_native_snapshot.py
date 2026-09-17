import hashlib,json,sys,tempfile,types,unittest
from datetime import date,datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.modules.setdefault('pymysql',types.ModuleType('pymysql'))
import crm_native_snapshot as snapshot
from crm_report_model import canonical


class NativeSnapshotTests(unittest.TestCase):
    def manifest(self,**changes):
        result=dict(source_code='xhs_order_api',time_field='order_created_at',api_time_type=3,
            conditions_verified=True,result_refresh_verified=True,identity_verified=True,
            contradiction_count=0,api_total=2,source_rows=2,unique_packages=2,
            requested_start_ms=int(datetime(2024,11,17,tzinfo=snapshot.SHANGHAI).timestamp()*1000),
            requested_end_ms=int(datetime(2026,9,16,tzinfo=snapshot.SHANGHAI).timestamp()*1000)-1,
            query_finished_at='2026-09-16T06:50:10Z')
        return {**result,**changes}

    def test_complete_history_endpoint_and_timezone(self):
        start,end,observed=snapshot.validate_scope(self.manifest(),{'opened_on':date(2024,11,17)},2)
        self.assertEqual((start,end,observed),(datetime(2024,11,17),datetime(2026,9,16),datetime(2026,9,16,14,50,10)))

    def test_latest_date_short_page_and_late_opening_do_not_prove_coverage(self):
        for change in [dict(api_total=3),dict(identity_verified=False),dict(contradiction_count=1),
                       dict(query_finished_at='2026-09-15T23:00:00+08:00')]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                snapshot.validate_scope(self.manifest(**change),{'opened_on':date(2024,11,17)},2)
        with self.assertRaisesRegex(ValueError,'full creation history'):
            snapshot.validate_scope(self.manifest(),{'opened_on':date(2024,11,16)},2)

    def test_signature_detects_shipping_update_but_normalizes_purchase_quantity(self):
        row=dict(line_key='l',order_key='o',code='A*3',quantity='1.0000',paid_at=datetime(2026,9,1),
                 shipped=False,sales_identity_known=True)
        self.assertEqual(snapshot.sales_signature([row]),snapshot.sales_signature([{**row,'quantity':1}]))
        self.assertNotEqual(snapshot.sales_signature([row]),snapshot.sales_signature([{**row,'shipped':True}]))
        self.assertNotEqual(snapshot.sales_signature([row]),snapshot.sales_signature([{**row,'code':'A*6'}]))

    def test_changed_original_or_current_native_data_cannot_reuse_certification(self):
        proof=dict(platform='xiaohongshu',shop_key='s',coverage_start='2024-11-17',coverage_end='2026-09-16',
                   observed_at='2026-09-16 14:50:10',manifest_path='/evidence/manifest',original_path='/evidence/original',current_signature='old')
        row={**proof,'proof_id':hashlib.sha256(canonical(proof).encode()).hexdigest(),'evidence_json':canonical(proof)}
        with patch('crm_sales_sources.query',return_value=[row]),patch.object(snapshot,'certify_xhs',return_value={**proof,'current_signature':'changed'}):
            with self.assertRaisesRegex(ValueError,'changed since certification'):
                snapshot.verified_snapshots(object(),date(2026,9,16))

    def test_other_shop_and_duplicate_original_package_are_rejected(self):
        from unittest.mock import Mock
        p=dict(packageId='p',sellerId='wrong',orderedAt='2026-09-01',skus=[{'skuId':'s'}])
        with self.assertRaisesRegex(ValueError,'outside shop'):
            snapshot.xhs_original_sales([p],Mock(),'right',datetime(2026,9,1),datetime(2026,9,2))
        p.update(sellerId='right')
        with self.assertRaisesRegex(ValueError,'duplicated'):
            snapshot.xhs_original_sales([p,p],Mock(),'right',datetime(2026,9,1),datetime(2026,9,2))


if __name__=='__main__':unittest.main()
