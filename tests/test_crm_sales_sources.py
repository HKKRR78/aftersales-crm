import sys
import types
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.modules.setdefault('pymysql',types.ModuleType('pymysql'))
import crm_sales_sources as sources

class NativeSalesTests(unittest.TestCase):
    def test_multi_day_native_read_preserves_each_original_version(self):
        shops=Mock();shops.by_key={('wechat_shop','shop'): {}};shops.resolve.return_value=('wechat_shop','shop')
        rows=[self.row(order_no='first',paid_at=datetime(2026,9,1),version_at=datetime(2026,9,4),native_shipments=None),
              self.row(order_no='second',source_key='second-line',paid_at=datetime(2026,9,2),version_at=datetime(2026,9,5),native_shipments=None)]
        with patch.object(sources,'query',side_effect=[[rows[0]],[rows[1]]]) as read, \
             patch('crm_wechat_shipping.restore_shipments') as restore:
            result=list(sources.read_sales(object(),shops,date(2026,9,1),date(2026,9,3),selected_platforms={'wechat_shop'}))
        self.assertEqual([s['order_no'] for s in result],['first','second'])
        self.assertEqual([s['quantity'] for s in result],[Decimal(1),Decimal(1)])
        self.assertEqual([call.args[2][-2:] for call in read.call_args_list],
                         [(date(2026,9,1),date(2026,9,2)),(date(2026,9,2),date(2026,9,3))])
        restore.assert_called_once();self.assertEqual(restore.call_args.args[1],rows)
        self.assertEqual([r['version_at'] for r in restore.call_args.args[1]],
                         [datetime(2026,9,4),datetime(2026,9,5)])

    def test_original_xhs_sku_purchase_segments_reconcile_without_counting_packages(self):
        raw=dict(skuQuantity=5,compositeFlag=False,childSkus=[],scskus=[
            dict(skuId='sku',scskuCode='real-pack',quantity=2),
            dict(skuId='sku',scskuCode='real-pack',quantity=3)])
        row=self.row(order_no='package',native_order_no='original-order',native_sku_id='sku',
                     sales_item_json=raw,quantity=5)
        sources.verify_xhs_sales_rows([row]);self.assertTrue(row['sales_identity_verified'])
        self.assertEqual(row['code'],'real-pack')
        duplicate={**row,'order_no':'second-package'}
        sources.verify_xhs_sales_rows([row,duplicate]);self.assertFalse(row['sales_identity_verified'])
        self.assertFalse(duplicate['sales_identity_verified'])
        mismatch={**row,'quantity':4}
        sources.verify_xhs_sales_rows([mismatch]);self.assertFalse(mismatch['sales_identity_verified'])

    def test_source_composite_item_key_requires_exact_product_and_unique_native_line(self):
        shops=Mock();shops.resolve.return_value=('pinduoduo','shop')
        sale=sources.normalize_sale(self.row(),'pinduoduo',{'table':'native'},shops)
        fact=dict(_shop=('pinduoduo','shop'),source_system='ticket_service',source_ticket_id='1',
                  source_item_id='2',order_no='order',sub_order_no='order:link',aftersales_product_id='link')
        orders={('pinduoduo','shop','order'):{sale['line_key']:sale}}
        sources.bridge_ticket_product_keys([fact],orders)
        self.assertIn('order:link',sale['sub_keys'])
        sale['sub_keys'].remove('order:link')
        sources.bridge_ticket_product_keys([{**fact,'aftersales_product_id':'other'}],orders)
        self.assertNotIn('order:link',sale['sub_keys'])
        other={**sale,'line_key':'second','code':'different-pack'}
        orders[('pinduoduo','shop','order')]['second']=other
        sources.bridge_ticket_product_keys([fact],orders)
        self.assertNotIn('order:link',sale['sub_keys'])

    def test_official_erp_shop_id_resolves_to_the_native_shop(self):
        row={'shop_sk':1,'platform_code':'wechat_shop','platform_shop_id':'native-appid',
             'shop_name_current':'正式店铺','wdt_shop_id':'p-56'}
        with patch.object(sources,'query',side_effect=[[row],[]]):shops=sources.Shops(object())
        self.assertEqual(shops.resolve('weixin','p-56','微信小店-历史名称'),('wechat_shop','native-appid'))

    def test_erp_suborder_bridge_requires_exact_native_product_and_sku_ids(self):
        shops=Mock();shops.resolve.return_value=('wechat_shop','shop')
        sale=sources.normalize_sale(self.row(native_sku_id='native-sku'),'wechat_shop',{'table':'native'},shops)
        row=dict(id=1,platform_id='83',shop_no='erp-shop',shop_name='name',
                 native_order_no='order',source_sub_order_no='order_001',native_product_id='link',native_sku_id='native-sku')
        orders={('wechat_shop','shop','order'):{sale['line_key']:sale}}
        facts=[{'_shop':('wechat_shop','shop'),'order_no':'order','sub_order_no':'order_001','logistics_no':'tracking'}]
        with patch.object(sources,'query',side_effect=[[{'wdt_platform_id':'83','canonical_platform_code':'wechat_shop'}],[row]]):
            sources.bridge_source_suborders(object(),shops,facts,orders)
        self.assertIn('order_001',sale['sub_keys'])
        self.assertEqual(sale['evidence']['suborder_bridges'][0]['id'],1)
        self.assertFalse(sources.exact_native_ids(sale,{**row,'native_sku_id':'different-pack'}))

    def row(self,**changes):
        row=dict(shop_id='shop',shop_name='name',order_no='order',sub_no='sub',source_key='line',
                 code='A*3+B*6',quantity=1,product_id='link',native_sku_id='sku',paid_at=datetime(2026,9,1),
                 ship_time=None,status='已发货',source_hash='hash')
        row.update(changes);return row
    def normalized(self,**changes):
        shops=Mock();shops.resolve.return_value=('douyin','shop')
        return sources.normalize_sale(self.row(**changes),'douyin',{'table':'native'},shops)
    def test_full_pack_code_and_original_purchase_quantity(self):
        sale=self.normalized();self.assertEqual(sale['code'],'A*3+B*6');self.assertEqual(sale['quantity'],Decimal(1))
    def test_import_hash_changes_do_not_create_another_native_sale(self):
        old=self.normalized(source_key='old-import-hash')
        new=self.normalized(source_key='new-import-hash')
        self.assertEqual(old['line_key'],new['line_key'])
        self.assertNotEqual(old['evidence']['row_key'],new['evidence']['row_key'])
        self.assertNotEqual(old['line_key'],self.normalized(sub_no='another-real-child')['line_key'])
        with self.assertRaisesRegex(ValueError,'child identity missing'):
            self.normalized(sub_no='')
    def test_wechat_identity_survives_old_import_hash_and_distinguishes_native_skus(self):
        shops=Mock();shops.resolve.return_value=('wechat_shop','shop')
        def sale(**changes):
            return sources.normalize_sale(self.row(**changes),'wechat_shop',{'table':'native'},shops)
        old=sale(source_key='old-three-field-import-hash')
        new=sale(source_key='new-four-field-import-hash')
        self.assertEqual(old['line_key'],new['line_key'])
        self.assertNotEqual(old['evidence']['row_key'],new['evidence']['row_key'])
        self.assertNotEqual(old['line_key'],sale(native_sku_id='another-pack')['line_key'])
        self.assertNotEqual(old['line_key'],sale(product_id='another-link')['line_key'])
        with self.assertRaisesRegex(ValueError,'product/SKU identity missing'):
            sale(native_sku_id='')
    def test_missing_quantity_is_not_zero(self):
        with self.assertRaisesRegex(ValueError,'missing original'):
            self.normalized(quantity=None)
    def test_refund_does_not_remove_proven_shipment(self):
        self.assertTrue(self.normalized(status='退款成功',ship_time=datetime(2026,9,2))['shipped'])
    def test_explicit_unshipped_refund_is_not_an_unknown_shipment(self):
        sale=self.normalized(status='未发货，退款成功')
        self.assertFalse(sale['shipped']);self.assertTrue(sale['shipping_known'])
    def test_tgc_order_and_link_follow_original_store_not_supplier_account(self):
        shops=Mock();shops.resolve.return_value=('tgc','supplier-a')
        first=sources.normalize_sale(self.row(native_shop_id='store',native_supplier_id='supplier-a'),'tgc',{'table':'native'},shops)
        shops.resolve.return_value=('tgc','supplier-b')
        second=sources.normalize_sale(self.row(source_key='other-line',native_shop_id='store',native_supplier_id='supplier-b'),'tgc',{'table':'native'},shops)
        self.assertEqual(first['order_key'],second['order_key'])
        self.assertEqual(first['line_key'],second['line_key'])
        self.assertEqual(first['link_key'],second['link_key'])
        self.assertEqual(first['shop_key'],'store');self.assertEqual(first['lookup_shop_key'],'supplier-a')
        with self.assertRaisesRegex(ValueError,'storefront identity missing'):
            sources.normalize_sale(self.row(),'tgc',{'table':'native'},shops)
    def test_warehouse_cannot_be_inferred_from_the_parent(self):
        sale=self.normalized(status='退款成功');proof={('douyin','shop','order'):[{'source_sub_order_no':'other','warehouse_name':'W','business_key':'proof'}]}
        sources.attach_shipping(sale,proof);self.assertFalse(sale['shipped']);self.assertEqual(sale['warehouse'],'')
    def test_split_warehouse_keeps_sale_once_without_claiming_one_warehouse(self):
        sale=self.normalized(status='退款成功',quantity=2)
        proof={('douyin','shop','order'):[self.fulfillment(warehouse_no=name,business_key=name) for name in ['W1','W2']]}
        sources.attach_shipping(sale,proof);self.assertTrue(sale['shipped']);self.assertEqual(sale['warehouse'],'');self.assertEqual(sale['quantity'],2)
    def fulfillment(self,**changes):
        row=dict(source_sub_order_no='sub',merchant_code='A*3+B*6',qty=1,stockout_no='stockout',
                 logistics_no='waybill',native_trade_type='1',native_stockout_type='1',business_key='real-proof',warehouse_no='warehouse')
        row.update(changes);return row
    def test_component_partial_and_replacement_do_not_certify_whole_original_purchase(self):
        for proof in [self.fulfillment(merchant_code='A',qty=3),self.fulfillment(qty=0.5),self.fulfillment(native_trade_type='7')]:
            sale=self.normalized(status='退款成功')
            sources.attach_shipping(sale,{('douyin','shop','order'):[proof]})
            self.assertFalse(sale['shipping_known']);self.assertFalse(sale['shipped']);self.assertEqual(sale['warehouse'],'')
    def test_exact_fulfillment_deduplicates_proof_and_preserves_native_quantity(self):
        sale=self.normalized(status='退款成功');proof=self.fulfillment()
        sources.attach_shipping(sale,{('douyin','shop','order'):[proof,proof]})
        self.assertTrue(sale['shipped']);self.assertEqual(sale['quantity'],1);self.assertEqual(sale['warehouse'],'warehouse')
    def test_sales_link_is_scoped_to_the_native_shop(self):
        shops=Mock();shops.resolve.return_value=('douyin','different-shop')
        other=sources.normalize_sale(self.row(),'douyin',{'table':'native'},shops)
        self.assertNotEqual(other['link_key'],self.normalized()['link_key'])
    def test_package_feed_cannot_certify_original_sales_line(self):
        shops=Mock();shops.resolve.return_value=('xiaohongshu','shop')
        one=sources.normalize_sale(self.row(order_no='package1',native_order_no='actual-order'),'xiaohongshu',{'table':'packages'},shops)
        two=sources.normalize_sale(self.row(order_no='package2',native_order_no='actual-order'),'xiaohongshu',{'table':'packages'},shops)
        self.assertEqual(one['order_key'],two['order_key'])
        self.assertFalse(one['sales_identity_known'])
        self.assertEqual(one['evidence']['sales_identity_reason'],'package_to_sales_line_unverified')

if __name__=='__main__':unittest.main()
