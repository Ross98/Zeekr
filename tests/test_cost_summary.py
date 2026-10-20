"""One actual-money definition for overview and books; synthetic records only."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.personal_store import PersonalStore
from zeekr_control.cost_summary import CostsSummary


class CostsSummaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / 'private'
        self.store = PersonalStore(self.root / 'personal.sqlite3')
        self.summary = CostsSummary(self.store, self.root / 'tracks.sqlite3')

    def save(self, collection, identity, body):
        revision = self.store.read('owner', 'car', collection)['revision']
        return self.store.change('owner', 'car', collection, 'save', identity, body, revision)

    def test_actual_total_is_charging_parking_and_life_without_estimates(self):
        self.save('charges', 'charge', dict(date='2026-10-08', actual_cents=10000,
            parking_fee_cents=2000, unit_price='9', metered_kwh=100, event=None))
        self.save('expenses', 'wash', dict(date='2026-10-08', amount_cents=5000,
            category='洗车', title='合成洗车'))
        value = self.summary.query('owner', 'car', '2026-10-08')
        self.assertEqual(value['totals']['actual_cents'], 17000)
        self.assertEqual(value['totals']['charge_cents'], 10000)
        self.assertEqual(value['totals']['charge_parking_cents'], 2000)
        self.assertEqual(value['totals']['life_cents'], 5000)
        self.assertEqual(value['revisions'], {'charges': 1, 'expenses': 1})

    def test_empty_unknown_zero_deleted_and_other_month_are_distinct(self):
        self.assertIsNone(self.summary.query('owner', 'car', '2026-10-01')['totals']['actual_cents'])
        self.assertFalse(self.root.exists(), 'readonly empty query must not create private storage')
        self.save('charges', 'unknown', dict(date='2026-10-08', actual_cents=None, parking_fee_cents=0))
        self.assertIsNone(self.summary.query('owner', 'car', '2026-10-01')['totals']['actual_cents'])
        self.save('expenses', 'free', dict(date='2026-10-08', amount_cents=0, category='洗车', title='免费'))
        self.save('expenses', 'prior', dict(date='2026-09-01', amount_cents=99999, category='其他', title='上月'))
        totals = self.summary.query('owner', 'car', '2026-10-01')['totals']
        self.assertEqual(totals['actual_cents'], 0)
        self.assertEqual(totals['unknown_charge_count'], 1)
        self.store.change('owner', 'car', 'expenses', 'delete', 'free', None, 2)
        self.assertIsNone(self.summary.query('owner', 'car', '2026-10-01')['totals']['actual_cents'])
        self.assertIsNone(self.summary.query('another', 'car', '2026-10-01')['totals']['actual_cents'])

    def test_duplicate_parking_is_a_hint_not_an_automatic_deduction(self):
        self.save('charges', 'charge', dict(date='2026-10-08', actual_cents=None, parking_fee_cents=2000))
        self.save('expenses', 'parking', dict(date='2026-10-08', amount_cents=2000, category='停车', title='停车'))
        value = self.summary.query('owner', 'car', '2026-10-01')
        self.assertEqual(value['totals']['actual_cents'], 4000)
        self.assertEqual([row['id'] for row in value['duplicates']], ['parking'])

    def test_read_many_uses_one_database_snapshot(self):
        self.save('charges', 'one', {'actual_cents': 1})
        self.save('expenses', 'two', {'amount_cents': 2})
        writer = sqlite3.connect(self.store.path)
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('UPDATE revisions SET revision=revision')
        writer.commit()
        original = self.store._read
        changed = []
        def read(db, key):
            value = original(db, key)
            if not changed:
                changed.append(True)
                self.store.change('owner', 'car', 'expenses', 'save', 'two', {'amount_cents': 3}, 1)
            return value
        with patch.object(self.store, '_read', side_effect=read):
            # The writer calls _read too, so mark the injection before entering it.
            result = self.store.read_many('owner', 'car', ['charges', 'expenses'])
        self.assertEqual(result['expenses']['records'][0]['body']['amount_cents'], 2)
        self.assertEqual(self.store.read('owner', 'car', 'expenses')['records'][0]['body']['amount_cents'], 3)

    def test_charts_use_actual_categories_and_six_months_from_one_snapshot(self):
        self.save('charges', 'bill', dict(date='2026-10-08', actual_cents=1000, parking_fee_cents=200))
        self.save('charges', 'pending', dict(date='2026-10-09', actual_cents=None, estimated_cents=9000, parking_fee_cents=0))
        self.save('expenses', 'custom', dict(date='2026-10-08', amount_cents=3000, category='自定义养护', title='真实分类'))
        self.save('expenses', 'free', dict(date='2026-10-09', amount_cents=0, category='免费服务', title='免费'))
        self.save('expenses', 'prior', dict(date='2026-05-01', amount_cents=500, category='保险', title='旧账'))
        self.save('expenses', 'outside', dict(date='2026-04-30', amount_cents=999, category='范围外', title='不纳入'))
        with patch.object(self.store, 'read_many', wraps=self.store.read_many) as read:
            value = self.summary.query('owner', 'car', '2026-10-01')
        self.assertEqual(read.call_count, 1)
        chart = value['charts']
        categories = {r['category']: r['amount_cents'] for r in chart['categories']}
        self.assertEqual(categories, {'充电': 1000, '充电停车费': 200, '自定义养护': 3000, '免费服务': 0})
        self.assertEqual(sum(categories.values()), value['totals']['actual_cents'])
        self.assertEqual([r['month'] for r in chart['months']], ['2026-05','2026-06','2026-07','2026-08','2026-09','2026-10'])
        self.assertEqual(chart['months'][0]['actual_cents'], 500)
        self.assertIsNone(chart['months'][1]['actual_cents'])
        self.assertEqual(chart['months'][-1]['actual_cents'], 4200)
        self.assertEqual(chart['largest']['id'], 'custom')
        self.assertEqual(chart['largest']['recorded_cents'], 3000)
        other = self.summary.query('other', 'car', '2026-10-01')['charts']
        self.assertEqual(other['categories'], [])
        self.assertTrue(all(r['actual_cents'] is None for r in other['months']))
        self.assertIsNone(other['largest'])
        self.store.change('owner', 'car', 'expenses', 'delete', 'custom', None, 4)
        self.assertNotIn('自定义养护', {r['category'] for r in self.summary.query('owner', 'car', '2026-10-01')['charts']['categories']})

    def test_all_history_totals_paging_years_and_no_telemetry_scan(self):
        for index in range(13):
            self.save('expenses', 'old'+str(index), dict(date='2022-01-%02d' % (index+1), amount_cents=100, category='旧保养', title='旧账'))
        self.save('charges', 'bill', dict(date='2026-10-08', actual_cents=None, parking_fee_cents=200))
        self.save('expenses', 'free', dict(date='2026-10-09', amount_cents=0, category='免费服务', title='免费'))
        with patch.object(self.summary.events, 'between', side_effect=AssertionError('all-history must not scan telemetry')):
            value = self.summary.query('owner', 'car', '2026-10-01', 'all')
        self.assertEqual(value['totals']['actual_cents'], 1500)
        self.assertIsNone(value['totals']['unlinked_charge_count'])
        self.assertEqual(value['charts']['years'], ['2022', '2026'])
        self.assertEqual(value['charts']['year'], '2026')
        self.assertEqual(len(value['charts']['months']), 12)
        self.assertEqual(value['records']['total'], 15)
        self.assertEqual(len(value['records']['rows']), 10)
        self.assertEqual(value['window']['start_date'], '2022-01-01')
        next_page = self.summary.query('owner', 'car', '2026-10-01', 'all', 1)
        self.assertEqual(len(next_page['records']['rows']), 5)
        self.assertFalse({r['id'] for r in value['records']['rows']} & {r['id'] for r in next_page['records']['rows']})
        filtered = self.summary.query('owner', 'car', '2026-10-01', 'all', 0, '充电停车费', '2022')
        self.assertEqual(filtered['records']['total'], 1)
        self.assertEqual(filtered['charts']['year'], '2022')
        self.assertEqual(filtered['charts']['months'][0]['actual_cents'], 1300)
        self.assertEqual(filtered['totals']['actual_cents'], 1500, 'year and category filter must not narrow cumulative total')
        self.assertIsNone(self.summary.query('other', 'car', '2026-10-01', 'all')['totals']['actual_cents'])
        with self.assertRaises(ValueError):self.summary.query('owner','car','2026-10-01','invalid')

    def test_annual_chart_sums_all_months_and_ignores_trend_year_filter(self):
        self.save('expenses','old',dict(date='2022-02-01',amount_cents=1200,category='维修修复',title='维修'))
        self.save('expenses','free',dict(date='2024-01-01',amount_cents=0,category='服务包',title='免费'))
        self.save('charges','pending',dict(date='2025-01-01',actual_cents=None,parking_fee_cents=0))
        self.save('charges','charge',dict(date='2026-01-01',actual_cents=800,parking_fee_cents=200))
        self.save('expenses','current',dict(date='2026-10-01',amount_cents=300,category='保养',title='保养'))
        result=self.summary.query('owner','car','2026-10-01','all',0,'','2022')
        annual=result['charts']['annual']
        self.assertEqual([(r['year'],r['actual_cents']) for r in annual], [('2022',1200),('2024',0),('2025',None),('2026',1300)])
        self.assertEqual(sum(r['actual_cents'] or 0 for r in annual),result['totals']['actual_cents'])
        self.assertEqual(sum(c['amount_cents'] for c in annual[-1]['categories']),1300)
        self.assertEqual(self.summary.query('other','car','2026-10-01','all')['charts']['annual'],[])
        self.assertEqual(self.summary.query('owner','car','2026-10-01')['charts']['annual'],[])
