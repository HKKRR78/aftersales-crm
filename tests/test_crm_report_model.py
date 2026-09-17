import json
import unittest
from datetime import date, datetime
from decimal import Decimal

from scripts.crm_report_model import SalesAggregation, legacy_current_facts, reconcile_source_facts, resolve_sale, source_fact_key


class SourceTruthTests(unittest.TestCase):
    def source(self, source, ticket, *, aftersale='refund', order='order', sub='sub', product='sku', problem='破损'):
        return dict(id=f'{source}-{ticket}',source_system=source,source_ticket_id=ticket,source_item_id='item',
                    api_created_at=datetime(2026,9,9),api_updated_at=datetime(2026,9,10),platform='抖音',shop_id='shop',shop_name='测试店',
                    order_no=order,sub_order_no=sub,aftersale_id=aftersale,aftersales_product_id=product,
                    merchant_code=product,problem1='产品问题',problem2=problem,problem3='')

    def test_same_order_or_base_code_without_event_proof_remains_two_issues(self):
        rows=[self.source('banniu','old',aftersale='old-refund'),self.source('ticket_service','new',aftersale='new-refund')]
        result=reconcile_source_facts(rows)
        self.assertEqual(len(result),2)
        self.assertEqual(sum(len(row['_source_inputs']) for row in result),2)

    def test_exact_cross_source_aftersale_identity_merges_and_conserves_refs(self):
        rows=[self.source('banniu','old'),self.source('ticket_service','new')]
        result=reconcile_source_facts(rows)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['source_system'],'banniu+ticket_service')
        self.assertEqual(len(result[0]['_source_inputs']),2)
        self.assertEqual(result[0]['_reconciliation_reason'],'exact_platform_aftersale_identity')

    def test_banniu_ticket_number_is_the_migrated_platform_aftersale_identity(self):
        old=self.source('banniu','old',aftersale='')
        old.update(ticket_no='refund',platform='',shop_id='')
        new=self.source('ticket_service','new',aftersale='refund')
        self.assertEqual(len(reconcile_source_facts([old,new])),1)

    def test_approved_mapping_merges_only_the_named_pair(self):
        rows=[self.source('banniu','old',aftersale='old-refund'),self.source('ticket_service','new',aftersale='new-refund')]
        mapping={'left_input_key':source_fact_key(rows[0]),'right_input_key':source_fact_key(rows[1])}
        result=reconcile_source_facts(rows,[mapping])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['_reconciliation_reason'],'approved_migration_mapping')

    def test_conflicting_mapping_or_exact_proof_blocks_candidate(self):
        left=self.source('banniu','old')
        right=self.source('ticket_service','new',problem='漏液')
        with self.assertRaisesRegex(ValueError,'conflict'):
            reconcile_source_facts([left,right])
        right['aftersale_id']='other'
        mapping={'left_input_key':source_fact_key(left),'right_input_key':source_fact_key(right)}
        with self.assertRaisesRegex(ValueError,'conflict'):
            reconcile_source_facts([left,right],[mapping])

    def test_latest_complete_task_retires_old_changed_child_key(self):
        old = {'13175': '', '13182': 'A'}
        new = {'13175': 'sub', '13182': 'A*3'}
        def row(i, child, children, synced):
            return dict(id=i, source_ticket_id='task', api_updated_at=synced, api_synced_at=synced,
                        raw_payload=json.dumps({'task': {'13174': json.dumps(children)}, 'child': child}))
        facts, retired = legacy_current_facts([row(1,old,[old],'2026-09-01'),row(2,new,[new],'2026-09-02')])
        self.assertEqual(retired,[1])
        self.assertEqual(len(facts),1)
        self.assertEqual(facts[0]['merchant_code'],'A*3')

    def test_existing_suborder_never_falls_back_to_parent(self):
        sales=[dict(line_key='line',sub_keys={'other'},code='A*3',sales_identity_known=True)]
        result=resolve_sale({'sub_order_no':'missing'},sales,order_complete=True)
        self.assertEqual(result['status'],'verified')
        self.assertEqual(result['reason'],'native_unique_complete_order_invalid_source_child')

    def test_same_base_multiple_pack_is_conflict(self):
        sales=[dict(sub_keys={'s'},code='A*3'),dict(sub_keys={'s'},code='A*6')]
        self.assertEqual(resolve_sale({'sub_order_no':'s'},sales)['status'],'conflict')

    def test_unique_parent_requires_completeness(self):
        sales=[dict(line_key='line',sub_keys={'s'},code='A*3',sales_identity_known=True)]
        self.assertEqual(resolve_sale({},sales)['status'],'missing')
        self.assertEqual(resolve_sale({},sales,order_complete=True)['code'],'A*3')

    def test_auxiliary_evidence_conflict_never_chooses_a_weighted_winner(self):
        sales=[
            dict(line_key='five',sub_keys={'other-1'},code='A*5',product_id='',native_sku_id='',
                 native_product_title='五袋装',native_logistics_no='WAYBILL',sales_identity_known=True),
            dict(line_key='twenty',sub_keys={'other-2'},code='A*20',product_id='',native_sku_id='',
                 native_product_title='二十袋装',native_logistics_no='',sales_identity_known=True),
        ]
        result=resolve_sale({'sub_order_no':'wrong','product_title':'二十袋装','logistics_no':'WAYBILL'},sales,order_complete=True)
        self.assertEqual(result['status'],'conflict')
        self.assertEqual(result['reason'],'evidence_conflict')
        self.assertEqual({row['line_key'] for row in result['sales']},{'five','twenty'})

    def test_missing_original_order_cannot_be_verified_from_catalog_or_intent(self):
        result=resolve_sale({'sub_order_no':'wrong','merchant_code':'A*5'},[],order_complete=False)
        self.assertEqual(result,{'status':'missing','reason':'original_sales_line_missing','code':'','sales':[]})

    def test_distinct_order_across_days_and_original_pack_quantity(self):
        a=SalesAggregation()
        for i,day,code in [(1,6,'A*3'),(2,7,'A*6')]:
            a.add(dict(line_key=str(i),order_key='same-order',paid_at=datetime(2026,9,day),
                       shipped=True,code=code,quantity=Decimal(1)))
        stats={(g,k):(n,qty) for start,end,g,k,n,qty in a.periods(date(2026,9,6),date(2026,9,13)) if end==date(2026,9,13)}
        self.assertEqual(stats['total','__all__'],(1,Decimal(2)))
        self.assertEqual(stats['merchant_code','A*3'],(1,Decimal(1)))
        self.assertEqual(stats['merchant_code','A*6'],(1,Decimal(1)))

    def test_duplicate_sales_line_cannot_double_count_or_hide_conflict(self):
        a=SalesAggregation();sale=dict(line_key='x',code='A*3')
        a.add(sale);a.add(sale)
        self.assertEqual(len(a.lines),1)
        with self.assertRaisesRegex(ValueError,'conflicting'):
            a.add(dict(line_key='x',code='A*6'))

    def test_known_sales_do_not_make_unknown_shipping_a_zero(self):
        a=SalesAggregation()
        a.add(dict(line_key='refunded',order_key='o',paid_at=datetime(2026,9,6),
                   shipped=False,shipping_known=False,code='A*3',quantity=Decimal(1)))
        coverage=a.coverage(date(2026,9,6),date(2026,9,7))
        invalid={(grain,key) for _,_,grain,key,complete,_ in coverage if not complete}
        self.assertIn(('total','__all__'),invalid)
        self.assertIn(('merchant_code','A*3'),invalid)

    def test_full_order_coverage_does_not_certify_a_missing_warehouse(self):
        a=SalesAggregation()
        a.add(dict(line_key='s',order_key='o',paid_at=datetime(2026,9,6),
                   shipped=True,shipping_known=True,code='A*3',link_key='L',warehouse='',quantity=Decimal(1)))
        coverage={grain:complete for _,_,grain,key,complete,_ in a.coverage(date(2026,9,6),date(2026,9,7)) if not key}
        self.assertEqual(coverage['total'],1)
        self.assertEqual(coverage['merchant_code'],1)
        self.assertEqual(coverage['warehouse'],0)
        self.assertEqual(coverage['warehouse_sales_link'],0)

    def test_verified_empty_day_is_zero_not_a_failed_collection(self):
        a=SalesAggregation()
        self.assertTrue(all(complete for _,_,_,_,complete,_ in a.coverage(date(2026,9,6),date(2026,9,7))))

    def test_unverified_package_quantity_cannot_enter_sales_or_become_zero(self):
        a=SalesAggregation()
        a.add(dict(line_key='package-sku',order_key='native-order',paid_at=datetime(2026,9,6),
                   shipped=True,shipping_known=True,sales_identity_known=False,
                   code='A*3',quantity=Decimal(9)))
        self.assertEqual(a.periods(date(2026,9,6),date(2026,9,7)),[])
        result=a.coverage(date(2026,9,6),date(2026,9,7))
        invalid={(grain,key):reason for _,_,grain,key,complete,reason in result if not complete}
        self.assertEqual(invalid['merchant_code','A*3'],'sales_line_identity_incomplete')
        self.assertEqual(invalid['total','__all__'],'sales_line_identity_incomplete')

    def test_one_uncertain_spec_does_not_hide_another_verified_spec(self):
        a=SalesAggregation()
        for code,known in [('A*3',False),('A*6',True)]:
            a.add(dict(line_key=code,order_key=code,paid_at=datetime(2026,9,6),
                       shipped=known,shipping_known=known,code=code,quantity=Decimal(1)))
        states={(grain,key):complete for _,_,grain,key,complete,_ in a.coverage(date(2026,9,6),date(2026,9,7))}
        self.assertEqual(states['merchant_code',''],1)
        self.assertEqual(states['merchant_code','A*3'],0)
        self.assertNotIn(('merchant_code','A*6'),states)
        self.assertEqual(states['total','__all__'],0)

    def test_unknown_spec_blocks_all_specs_instead_of_assigning_a_zero(self):
        a=SalesAggregation()
        a.add(dict(line_key='missing',order_key='o',paid_at=datetime(2026,9,6),
                   shipped=True,shipping_known=True,code='',quantity=Decimal(1)))
        states={(grain,key):complete for _,_,grain,key,complete,_ in a.coverage(date(2026,9,6),date(2026,9,7))}
        self.assertEqual(states['merchant_code',''],0)


if __name__=='__main__':
    unittest.main()
