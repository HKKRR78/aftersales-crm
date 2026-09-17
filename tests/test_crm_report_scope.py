import sys,unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from crm_report_scope import recent_release_scope,validate_release_scope


class ReleaseScopeTests(unittest.TestCase):
    def test_five_complete_weeks_and_existing_product_selector_comparisons(self):
        scope=recent_release_scope(date(2026,9,16))
        self.assertEqual((scope['displayStart'],scope['displayEnd']),('2026-08-09','2026-09-13'))
        # The earliest selected week Aug 9 displays Jul 12..Aug 15; the first
        # displayed column compares against Jul 5..11.
        self.assertEqual(scope['requiredStart'],'2026-07-05')
        self.assertIn({'start':'2026-09-13','end':'2026-09-16','kind':'progress'},scope['requiredPeriods'])
        self.assertIn({'start':'2026-09-06','end':'2026-09-09','kind':'progress'},scope['requiredPeriods'])
        self.assertEqual(validate_release_scope(scope,date(2026,7,5),date(2026,9,16)),scope)

    def test_sunday_has_no_completed_progress_days_and_rolls_across_year(self):
        scope=recent_release_scope(date(2027,1,3))
        self.assertEqual(scope['selectableReleaseWeeks'][-1],'2026-12-27')
        self.assertFalse(any(p['kind']=='progress' for p in scope['requiredPeriods']))

    def test_narrowed_comparison_scope_or_stale_scope_is_rejected(self):
        scope=recent_release_scope(date(2026,9,16))
        for changed in [{**scope,'requiredStart':'2026-08-09'}, {**scope,'requiredPeriods':scope['requiredPeriods'][:-1]}]:
            with self.assertRaisesRegex(ValueError,'required comparison'):
                validate_release_scope(changed,date(2026,7,5),date(2026,9,16))


if __name__=='__main__':unittest.main()
