import json,sys,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from tempfile import TemporaryDirectory
from crm_wechat_artifact import certify,registered_artifacts
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from crm_wechat_shipping import from_original
from crm_native_shipping import wechat_product_shipped


class WechatOriginalTests(unittest.TestCase):
    def sample(self):
        paid=datetime(2026,9,1,tzinfo=timezone(timedelta(hours=8)))
        updated=paid+timedelta(days=2)
        raw=dict(order_id='order',update_time=int(updated.timestamp()),order_detail={
            'pay_info':{'pay_time':int(paid.timestamp())},
            'product_infos':[{'product_id':'goods','sku_id':'sku','sku_code':'A*3','sku_cnt':2}],
            'delivery_info':{'address_info':{'user_name':'test-only'},'delivery_product_info':[
                {'delivery_id':'carrier','waybill_id':'tracking','delivery_time':int(updated.timestamp()),
                 'product_infos':[{'product_id':'goods','sku_id':'sku','product_cnt':2}]}]}})
        return dict(order_id='order',product_id='goods',sku_id='sku',sku_code='A*3',sku_cnt=2,
                    pay_time='2026-09-01 00:00:00',update_time='2026-09-03 00:00:00',raw_order_json=json.dumps(raw))

    def test_native_original_restores_exact_sku_shipping_without_address(self):
        key,original=from_original(self.sample())
        self.assertEqual(key,('order','goods','sku'))
        self.assertNotIn('address_info',json.dumps(original,default=str))
        self.assertTrue(wechat_product_shipped({'product_id':'goods','native_sku_id':'sku','quantity':2,'native_shipments':original['shipments']}))

    def test_different_spec_quantity_or_version_cannot_supply_shipping(self):
        for changes in [{'sku_code':'A*6'},{'sku_cnt':6},{'update_time':'2026-09-04 00:00:00'}, {'order_id':'other'}]:
            with self.assertRaises(ValueError):from_original({**self.sample(),**changes})

    def retained(self,root):
        from openpyxl import Workbook
        source=root/'orders.xlsx';evidence=root/'orders.source.json'
        wb=Workbook();ws=wb.active;ws.title='订单';row=self.sample()
        ws.append(list(row));ws.append(list(row.values()));wb.save(source);wb.close()
        value=dict(platform_code='wechat_shop',data_type='ORDER',source_code='wechat_order_api',
            platform_shop_id='native-appid',artifact_path=str(source),
            query=dict(conditions_verified=True,result_refresh_verified=True),
            summary=dict(candidate_unique_orders=1,detail_success_orders=1,detail_failed_orders=0,record_count=1))
        evidence.write_text(json.dumps(value))
        return source,evidence,value

    def test_archive_requires_source_identity_complete_details_and_exact_row_count(self):
        with TemporaryDirectory() as directory:
            source,evidence,value=self.retained(Path(directory))
            self.assertEqual(certify(source,evidence,'native-appid')['source_rows'],1)
            with self.assertRaises(ValueError):certify(source,evidence,'wrong-shop')
            value['summary']['detail_failed_orders']=1;evidence.write_text(json.dumps(value))
            with self.assertRaises(ValueError):certify(source,evidence,'native-appid')
            value['summary'].update(detail_failed_orders=0,record_count=2);evidence.write_text(json.dumps(value))
            with self.assertRaises(ValueError):certify(source,evidence,'native-appid')

    def test_registered_archive_rejects_changed_evidence(self):
        import hashlib
        from crm_report_model import canonical
        with TemporaryDirectory() as directory:
            source,evidence,value=self.retained(Path(directory));proof=certify(source,evidence,'native-appid')
            row=dict(shop_key='native-appid',source_filename=source.name,evidence_json=canonical(proof),
                     proof_id=hashlib.sha256(canonical(proof).encode()).hexdigest())
            with patch('crm_sales_sources.query',return_value=[row]):
                self.assertEqual(len(list(registered_artifacts(None,{('native-appid',source.name)}))),1)
                value['platform_shop_id']='wrong-shop';evidence.write_text(json.dumps(value))
                with self.assertRaises(ValueError):list(registered_artifacts(None,{('native-appid',source.name)}))

    def test_exact_gap_read_must_reconcile_every_original_item(self):
        import hashlib
        with TemporaryDirectory() as directory:
            root=Path(directory);source,evidence,value=self.retained(root);responses=root/'responses.jsonl'
            raw=json.loads(self.sample()['raw_order_json'])
            record=dict(endpoint='/channels/ec/order/get',request={'order_id':'order'},observed_at='2026-09-16T20:00:00+08:00',response={'order':raw})
            responses.write_text(json.dumps(record)+'\n')
            value['query'].update(kind='EXACT_ORDER_IDS',order_ids=['order'],responses_path=str(responses),responses_sha256=hashlib.sha256(responses.read_bytes()).hexdigest())
            evidence.write_text(json.dumps(value));self.assertEqual(certify(source,evidence,'native-appid')['source_rows'],1)
            raw['order_detail']['product_infos'][0]['sku_code']='A*6'
            responses.write_text(json.dumps(record)+'\n')
            value['query']['responses_sha256']=hashlib.sha256(responses.read_bytes()).hexdigest();evidence.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'API and original workbook differ'):certify(source,evidence,'native-appid')
