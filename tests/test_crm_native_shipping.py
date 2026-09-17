import csv,hashlib,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from crm_native_shipping import doudian_original_shipping,valid_ship_time,wechat_product_shipped


class NativeShippingTests(unittest.TestCase):
    def test_empty_or_invalid_time_does_not_prove_shipping(self):
        for value in [None,'','null','-','0000-00-00 00:00:00','待发货']:
            self.assertFalse(valid_ship_time(value))
        self.assertTrue(valid_ship_time('2026-09-01 12:00:00'))

    def test_original_ship_time_preserves_sale_after_refund_and_checks_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'original.csv'
            fields=['主订单编号','子订单编号','商品ID','商家编码','商品数量','发货时间']
            with path.open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(fields)
                writer.writerow(['order','sub','product','A*3','2','2026-09-01 12:00:00'])
            row=dict(source_file=str(path),source_file_hash=hashlib.sha1(path.read_bytes()).hexdigest(),
                     sub_no='sub',order_no='order',product_id='product',code='A*3',quantity=2,status='已关闭')
            doudian_original_shipping([row],lambda _:False)
            self.assertEqual(row['ship_time'],'2026-09-01 12:00:00')
            wrong={**row,'code':'A*6'};wrong.pop('ship_time')
            doudian_original_shipping([wrong],lambda _:False)
            self.assertNotIn('ship_time',wrong)
            self.assertEqual(wrong['shipping_source_reason'],'native_original_line_not_unique')
            path.write_text('changed')
            with self.assertRaisesRegex(ValueError,'original file changed'):
                doudian_original_shipping([row],lambda _:False)

    def test_wechat_exact_sku_shipments_do_not_count_other_or_duplicate_packages(self):
        shipment=dict(delivery_time=1700000000,delivery_id='carrier',waybill_id='waybill',
                      product_infos=[dict(product_id='product',sku_id='sku3',product_cnt=1)])
        row=dict(product_id='product',native_sku_id='sku3',quantity=1,native_shipments=[shipment,shipment])
        self.assertTrue(wechat_product_shipped(row))
        self.assertFalse(wechat_product_shipped({**row,'native_sku_id':'sku6'}))
        self.assertFalse(wechat_product_shipped({**row,'quantity':2}))
