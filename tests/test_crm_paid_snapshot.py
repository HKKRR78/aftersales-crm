import csv,sys,types,tempfile,unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.modules.setdefault('pymysql',types.ModuleType('pymysql'))
import crm_paid_snapshot as paid

class PaidSnapshotTests(unittest.TestCase):
    def source(self):
        query=dict(time_basis='PAID_AT',shop_id='shop',report_id='report',verified_at='2026-09-16T10:00:00Z',
            query=dict(pay_time_start=1783180800,pay_time_end=1789487999,report_type='STANDARD'))
        count=dict(http_status=200,code=0,shop_id='shop',total=1,
            query=dict(tab='all',pay_time_start=1783180800,pay_time_end=1789487999))
        history={**count,'total':0,'query':{**count['query'],'tab':'history'}}
        return query,count,history

    def test_native_paid_scope_requires_both_creation_tabs(self):
        query,count,history=self.source()
        self.assertEqual(paid.validate_query(query,count,history,'shop','report'),(datetime(2026,7,5),datetime(2026,9,16)))
        history['total']=1
        with self.assertRaisesRegex(ValueError,'older-creation'):
            paid.validate_query(query,count,history,'shop','report')

    def test_failed_empty_query_wrong_shop_and_clipped_date_cannot_certify_zero(self):
        for change in [dict(code=1,total=0),dict(total=None),dict(shop_id='other')]:
            query,count,history=self.source();count.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):paid.validate_query(query,count,history,'shop','report')

    def test_native_reconciliation_queries_one_paid_day_at_a_time(self):
        chunks=list(paid.payment_chunks(datetime(2026,9,13),datetime(2026,9,16)))
        self.assertEqual(chunks,[
            (datetime(2026,9,13),datetime(2026,9,14)),
            (datetime(2026,9,14),datetime(2026,9,15)),
            (datetime(2026,9,15),datetime(2026,9,16)),
        ])
        for field in ['create_time_start','status','sub_shop_id']:
            query,count,history=self.source();query['query'][field]=1
            with self.subTest(field=field),self.assertRaises(ValueError):paid.validate_query(query,count,history,'shop','report')

    def write_original(self,path,changes=None,duplicate=False):
        row={'主订单编号':'M','子订单编号':'S','商品ID':'P','商家编码':'A*3+B*6','商品数量':'2',
             '支付完成时间':'2026-07-05 00:01:00','订单提交时间':'2026-06-30 12:00:00','订单状态':'已关闭','发货时间':'2026-07-06 12:00:00'}
        row.update(changes or {})
        with path.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=row);w.writeheader();w.writerow(row)
            if duplicate:w.writerow(row)

    def test_original_created_before_scope_and_shipped_then_refunded_is_retained(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'original.csv';self.write_original(path)
            row=paid.read_douyin_original(path,datetime(2026,7,5),datetime(2026,9,16))['S']
        self.assertEqual(row[3],'A*3+B*6');self.assertEqual(row[4],'2')
        self.assertEqual(row[6],'2026-06-30 12:00:00');self.assertTrue(row[-2]);self.assertTrue(row[-1])

    def test_duplicates_missing_quantity_and_wrong_payment_window_fail_closed(self):
        cases=[({},True),({'商品数量':''},False),({'商品数量':'NaN'},False),({'支付完成时间':'2026-07-04 23:59:59'},False)]
        for change,duplicate in cases:
            with self.subTest(change=change,duplicate=duplicate),tempfile.TemporaryDirectory() as d:
                path=Path(d)/'original.csv';self.write_original(path,change,duplicate)
                with self.assertRaises(ValueError):paid.read_douyin_original(path,datetime(2026,7,5),datetime(2026,9,16))

if __name__=='__main__':unittest.main()
