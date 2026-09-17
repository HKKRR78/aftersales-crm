import sys,types,unittest
from decimal import Decimal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.modules.setdefault('pymysql',types.ModuleType('pymysql'))
from crm_pdd_original_proof import reconcile


class PddOriginalTests(unittest.TestCase):
    def original(self):
        return {'mall_id':'shop','订单号':'order','商品id':'product','样式ID':'sku3',
                '商家编码-规格维度':'A*3','商品数量(件)':Decimal(2)}

    def sale(self,**changes):
        return dict(platform='pinduoduo',shop_key='shop',order_no='order',product_id='product',
                    native_sku_id='sku3',code='A*3',quantity=Decimal(2),evidence={},**changes)

    def test_full_native_spec_and_order_set_must_agree(self):
        sale=self.sale();self.assertTrue(reconcile([sale],self.original(),{'file':'original'}))
        self.assertTrue(sale['original_order_complete'])
        for field,value in [('shop_key','another'),('code','A*6'),('quantity',Decimal(6)),('native_sku_id','sku6')]:
            changed=self.sale();changed[field]=value
            self.assertFalse(reconcile([changed],self.original(),{}))
            self.assertNotIn('original_order_complete',changed)
        self.assertFalse(reconcile([self.sale(),self.sale()],self.original(),{}))

    def test_complete_order_proof_does_not_override_explicit_wrong_child(self):
        from crm_report_model import resolve_sale
        sale=self.sale(sub_keys={'order'})
        self.assertTrue(reconcile([sale],self.original(),{}))
        self.assertEqual(resolve_sale({'sub_order_no':'wrong'},[sale],order_complete=True)['reason'],'native_unique_complete_order_invalid_source_child')


if __name__=='__main__':unittest.main()
