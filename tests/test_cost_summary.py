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
