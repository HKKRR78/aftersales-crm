import sys
import json
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.modules.setdefault('pymysql', types.ModuleType('pymysql'))
import crm_report_coverage as coverage


class CoverageTests(unittest.TestCase):
    def test_explicit_retired_tmall_identity_is_not_a_second_taobao_shop(self):
        shops=Mock();shops.by_key={
            ('tmall','native'):{'shop_sk':6,'is_active':0,'effective_end':'2026-08-30 16:06:56'},
            ('taobao','native'):{'shop_sk':74,'is_active':1},
            ('kuaishou','closed'):{'shop_sk':9,'is_active':0}}
        alias={'source_shop_id':'native','shop_sk':74,'updated_at':'2026-08-30 16:06:56'}
        scopes=[
            dict(platform_code='tmall',platform_shop_id='native',shop_name_observed='旧店',coverage_role='PRIMARY',
                 collection_status=None,effective_start='2026-01-01',effective_end='9999-12-31',source_code='tmall_order_rpa'),
            dict(platform_code='taobao',platform_shop_id='native',shop_name_observed='现店',coverage_role='PRIMARY',
                 collection_status=None,effective_start='2026-01-01',effective_end='9999-12-31',source_code='tmall_order_rpa'),
            dict(platform_code='kuaishou',platform_shop_id='closed',shop_name_observed='已关店',coverage_role='PRIMARY',
                 collection_status=None,effective_start='2026-01-01',effective_end='2026-07-22',source_code='kuaishou_order_rpa')]
        with patch.object(coverage,'query',side_effect=[scopes,[alias],[]]):
            result=coverage.reporting_shops(object(),shops,date(2026,7,5),date(2026,9,16))
        self.assertEqual(set(result),{('taobao','native'),('kuaishou','closed')})
        self.assertEqual(result['taobao','native']['retired_registry_identity']['shop_sk'],6)
        self.assertIn(('tmall','native'),shops.by_key)
        for wrong in [[],[{**alias,'shop_sk':75}],[{**alias,'updated_at':'2026-08-29 00:00:00'}]]:
            with patch.object(coverage,'query',side_effect=[scopes,wrong]):
                self.assertIn(('tmall','native'),coverage.reporting_shops(object(),shops,date(2026,7,5),date(2026,9,16)))
        with patch.object(coverage,'query',side_effect=[scopes,[alias],[{'sub_order_id':'real-conflicting-sale'}]]):
            with self.assertRaisesRegex(ValueError,'retired Tmall identity still owns native sales'):
                coverage.reporting_shops(object(),shops,date(2026,7,5),date(2026,9,16))

    def test_historical_dim_shop_outside_source_contract_is_not_a_release_shop(self):
        shops=Mock();shops.by_key={
            ('wechat_shop','current'):{'shop_name_current':'当前店','is_active':1},
            ('wechat_shop','historical'):{'shop_name_current':'旧店','is_active':0}}
        scopes=[dict(platform_code='wechat_shop',platform_shop_id='current',shop_name_observed='当前店',
                     coverage_role='PRIMARY',collection_status=None,effective_start='2026-01-01',
                     effective_end='9999-12-31',source_code='wechat_order_api')]
        with patch.object(coverage,'query',return_value=scopes):
            result=coverage.reporting_shops(object(),shops,date(2026,9,6),date(2026,9,13))
        self.assertEqual(set(result),{('wechat_shop','current')})

    def test_contract_effective_end_limits_required_days(self):
        shops=Mock();shops.by_key={('kuaishou','closed'):{'shop_name_current':'已关店','opened_on':None,'is_active':0}}
        shops.resolve.return_value=('kuaishou','closed')
        scope=dict(platform_code='kuaishou',platform_shop_id='closed',shop_name_observed='已关店',coverage_role='PRIMARY',
                   collection_status='CLOSED',effective_start='2026-01-01',effective_end='2026-09-07',source_code='kuaishou_order_rpa')
        with patch.object(coverage,'verified_snapshots',return_value={}),patch.object(coverage,'query',side_effect=[
            [scope],[{'source_code':'kuaishou_order_rpa','query_time_semantics':'ORDER_CREATED_AT'}],[]]):
            result=coverage.evidence(object(),shops,date(2026,9,6),date(2026,9,10))
        self.assertEqual([row[2] for row in result],[date(2026,9,6),date(2026,9,7)])

    def test_publication_rechecks_source_failure_and_added_shop_after_snapshot(self):
        row=('douyin','s',date(2026,9,6),'verified','official_paid_window_reconciled',{'native_snapshot':{'proof_id':'p'}})
        stored=dict(zip(('platform','shop_key','stat_date','status','reason','evidence_json'),(*row[:5],json.dumps(row[5]))))
        with patch.object(coverage,'query',return_value=[stored]),patch('crm_sales_sources.Shops'),patch.object(coverage,'evidence',return_value=[row]) as live:
            coverage.require_unchanged_coverage(object(),'batch',date(2026,9,6),date(2026,9,7))
            for changed in [[(*row[:3],'missing','newer_source_read_failed',{})],
                            [row,('douyin','new-store',date(2026,9,6),'missing','collection_evidence_missing',{})],
                            [(*row[:5],{'native_snapshot':{'proof_id':'new-original'}})]]:
                live.return_value=changed
                with self.assertRaisesRegex(ValueError,'source coverage changed or failed'):
                    coverage.require_unchanged_coverage(object(),'batch',date(2026,9,6),date(2026,9,7))

    def test_tgc_uses_original_storefronts_including_registered_zero_sales(self):
        shops=Mock();shops.by_key={('tgc','supplier'):{},('douyin','ordinary'):{}}
        scope_rows=[
            dict(platform_code='tgc',platform_shop_id='A',shop_name_observed='店 A',coverage_role='PRIMARY',
                 collection_status=None,effective_start='2026-01-01',effective_end='9999-12-31',source_code='tgc_order_rpa'),
            dict(platform_code='tgc',platform_shop_id='B',shop_name_observed='店 B',coverage_role='PRIMARY',
                 collection_status=None,effective_start='2026-01-01',effective_end='9999-12-31',source_code='tgc_order_rpa'),
            dict(platform_code='douyin',platform_shop_id='ordinary',shop_name_observed='普通店',coverage_role='PRIMARY',
                 collection_status=None,effective_start='2026-01-01',effective_end='9999-12-31',source_code='doudian_order_rpa')]
        with patch.object(coverage,'query',side_effect=[
            scope_rows,
            [{'platform_shop_id':'A','shop_name_observed':'店 A','effective_start':'2026-01-01','effective_end':'9999-12-31'},
             {'platform_shop_id':'B','shop_name_observed':'店 B','effective_start':'2026-01-01','effective_end':'9999-12-31'}],
            [{'platform_shop_id':'A'},{'platform_shop_id':'C'}]]):
            result=coverage.reporting_shops(object(),shops,date(2026,9,6),date(2026,9,8))
        self.assertEqual(set(result),{('tgc','A'),('tgc','B'),('tgc','C'),('douyin','ordinary')})
        self.assertTrue(result['tgc','B']['registered_storefront'])
        self.assertFalse(result['tgc','C']['registered_storefront'])

    def test_tgc_audit_uses_actual_storefront_and_keeps_unknown_identity_blocked(self):
        shops=Mock();shops.by_key={('tgc','supplier'):{}}
        row=dict(platform_code='tgc',platform_shop_id='A',source_code='tgc_order_rpa',
                 business_date='2026-09-06',loaded_at='2026-09-07',row_count=5,
                 zero_data_confirmed=0,completeness_status='READY')
        snapshot=dict(coverage_start='2026-09-06',coverage_end='2026-09-08',proof_id='p')
        scope_rows=[dict(platform_code='tgc',platform_shop_id='A',shop_name_observed='店 A',coverage_role='PRIMARY',
                         collection_status=None,effective_start='2026-01-01',effective_end='9999-12-31',source_code='tgc_order_rpa')]
        with patch.object(coverage,'verified_snapshots',return_value={('tgc','C'):snapshot}),patch.object(coverage,'query',side_effect=[
            scope_rows,
            [{'platform_shop_id':'A','shop_name_observed':'店 A','effective_start':'2026-01-01','effective_end':'9999-12-31'}],
            [{'platform_shop_id':'A'},{'platform_shop_id':'C'}],
            [{'source_code':'tgc_order_rpa','query_time_semantics':'PAID_AT'}],[row]]):
            result=coverage.evidence(object(),shops,date(2026,9,6),date(2026,9,7))
        self.assertEqual(result[0][3:5],('verified','official_paid_window_reconciled'))
        self.assertEqual(result[1][3:5],('missing','storefront_identity_unverified'))
        shops.resolve.assert_not_called()

    def result(self, semantics='ORDER_CREATED_AT', **overrides):
        shops = Mock()
        shops.by_key = {('douyin', 's'): {'shop_name_current': '店铺', 'opened_on': None, 'is_active': 1}}
        shops.resolve.return_value = ('douyin', 's')
        row = dict(platform_code='douyin', platform_shop_id='s', source_code='doudian_order_rpa',
                   business_date='2026-09-06', loaded_at='2026-09-07', row_count=5,
                   zero_data_confirmed=0, completeness_status='READY')
        row.update(overrides)
        scope=dict(platform_code='douyin',platform_shop_id='s',shop_name_observed='店铺',coverage_role='PRIMARY',
                   collection_status=None,effective_start='2026-01-01',effective_end='9999-12-31',source_code='doudian_order_rpa')
        with patch.object(coverage,'verified_snapshots',return_value={}),patch.object(coverage, 'query', side_effect=[
            [scope],[{'source_code': row['source_code'], 'query_time_semantics': semantics}], [row]]):
            return coverage.evidence(object(), shops, date(2026, 9, 6), date(2026, 9, 8))

    def test_successful_creation_window_does_not_certify_paid_window(self):
        self.assertEqual(self.result()[0][3:5], ('missing', 'payment_window_not_reconciled'))

    def test_empty_query_requires_explicit_zero_proof(self):
        self.assertEqual(self.result('PAID_AT', row_count=0)[0][4], 'zero_not_verified')
        self.assertEqual(self.result('PAID_AT', row_count=0, zero_data_confirmed=1)[0][3], 'verified')

    def test_auxiliary_source_does_not_certify_native_source(self):
        self.assertEqual(self.result('PAID_AT', source_code='reduyun_order_rpa')[0][4], 'collection_evidence_missing')

    def test_latest_success_does_not_certify_another_missing_day(self):
        result = self.result('PAID_AT')
        self.assertEqual(result[0][3], 'verified')
        self.assertEqual(result[1][3], 'missing')

    def test_reconciled_full_history_certifies_only_its_shop_and_dates(self):
        shops=Mock();shops.by_key={('xiaohongshu','s'):{'shop_name_current':'店','opened_on':None,'is_active':1}}
        proof={'coverage_start':'2026-09-06','coverage_end':'2026-09-08','proof_id':'p'}
        scope=dict(platform_code='xiaohongshu',platform_shop_id='s',shop_name_observed='店',coverage_role='PRIMARY',
                   collection_status=None,effective_start='2026-01-01',effective_end='9999-12-31',source_code='xhs_order_api')
        with patch.object(coverage,'query',side_effect=[[scope],[],[]]),patch.object(coverage,'verified_snapshots',return_value={('xiaohongshu','s'):proof}):
            result=coverage.evidence(object(),shops,date(2026,9,5),date(2026,9,9))
        self.assertEqual([r[3] for r in result],['missing','verified','verified','missing'])

    def test_earlier_snapshot_does_not_hide_a_newer_source_failure(self):
        shops=Mock();shops.by_key={('douyin','s'):{'shop_name_current':'店','opened_on':None,'is_active':1}}
        shops.resolve.return_value=('douyin','s')
        snapshot=dict(coverage_start='2026-09-06',coverage_end='2026-09-08',proof_id='p',
                      source_kind='official_paid_export',observed_at='2026-09-08 10:00:00')
        failed=dict(platform_code='douyin',platform_shop_id='s',source_code='doudian_order_rpa',
                    business_date='2026-09-06',loaded_at='2026-09-08 11:00:00',completeness_status='BLOCKED')
        scope=dict(platform_code='douyin',platform_shop_id='s',shop_name_observed='店',coverage_role='PRIMARY',
                   collection_status=None,effective_start='2026-01-01',effective_end='9999-12-31',source_code='doudian_order_rpa')
        with patch.object(coverage,'query',side_effect=[[scope],[],[failed]]),patch.object(coverage,'verified_snapshots',return_value={('douyin','s'):snapshot}):
            result=coverage.evidence(object(),shops,date(2026,9,6),date(2026,9,8))
        self.assertEqual(result[0][3:5],('missing','newer_source_read_failed'))
        self.assertEqual(result[1][3:5],('verified','official_paid_window_reconciled'))


if __name__ == '__main__':
    unittest.main()
