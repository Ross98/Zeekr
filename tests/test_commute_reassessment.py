"""Evidence retry, explicit historical review, and automatic collection tests."""
import json
import sqlite3
from unittest.mock import patch

from tests import test_commute_tags as fixtures


class CommuteReassessmentTests(fixtures.CommuteTagTests):
    def test_late_endpoint_samples_retry_without_rule_change(self):
        effective = self.save_rule()['effective_at']
        self.trip('late', effective + 1000, (31.2, 121.4), (31.21, 121.41))
        with sqlite3.connect(self.db) as db:
            rows = db.execute('SELECT * FROM observations').fetchall()
            db.execute('DELETE FROM observations')
        self.assertEqual(self.tags.query('owner', 'car', '2026-09-28')['events'][0]['commute_reason'], 'insufficient')
        with sqlite3.connect(self.db) as db:
            db.executemany('INSERT INTO observations VALUES(?,?,?,?,?,?,?)', rows)
        row = self.tags.query('owner', 'car', '2026-09-28')['events'][0]
        self.assertTrue(row['automatic_commute'])
        self.assertEqual(row['commute_evidence']['direction'], 'outbound')
        self.assertAlmostEqual(row['commute_evidence']['start_distance_m'], 0)

    def test_unchanged_insufficient_evidence_does_not_write_again(self):
        effective = self.save_rule()['effective_at']
        self.trip('bad', effective + 1000, (31.2, 121.4), (31.21, 121.41), trusted=False)
        self.tags.query('owner', 'car', '2026-09-28')
        with patch.object(self.tags.store, 'connect', wraps=self.tags.store.connect) as connect:
            self.tags.query('owner', 'car', '2026-09-28')
        self.assertFalse(any(call.kwargs.get('write') for call in connect.call_args_list))

    def test_partial_match_has_explicit_evidence_warning(self):
        effective = self.save_rule()['effective_at']
        self.trip('partial', effective + 1000, (31.21, 121.41), (31.2, 121.4))
        with sqlite3.connect(self.db) as db:
            data = json.loads(db.execute('SELECT summary FROM monitor_events').fetchone()[0])
            data['partial'] = True
            db.execute('UPDATE monitor_events SET summary=?', (json.dumps(data),))
        row = self.tags.query('owner', 'car', '2026-09-28')['events'][0]
        self.assertTrue(row['automatic_commute'])
        self.assertTrue(row['commute_evidence']['partial'])
        self.assertEqual(row['commute_evidence']['direction'], 'backward')

    def preview(self):
        return self.tags.update('owner', 'car', dict(action='commute-preview', date='2026-09-28', revision=1))

    def apply(self, preview, **extra):
        payload = dict(action='commute-apply', date='2026-09-28', revision=1, token=preview['token'])
        payload.update(extra)
        return self.tags.update('owner', 'car', payload)

    def test_historical_preview_is_readonly_and_apply_preserves_manual_labels(self):
        self.trip('old', self.start + 1000, (31.2, 121.4), (31.21, 121.41))
        self.save_rule()
        self.tags.update('owner', 'car', dict(action='save', event_id='old', tags=['接娃'], note='保留', revision=0))
        preview = self.preview()
        self.assertEqual(preview['counts']['add'], 1)
        self.assertEqual(preview['rows'][0]['direction'], 'outbound')
        with self.tags.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM commute_decisions').fetchone()[0], 0)
        self.apply(preview)
        row = self.tags.query('owner', 'car', '2026-09-28')['events'][0]
        self.assertEqual(row['tags'], ['接娃', '通勤'])
        self.assertEqual(row['note'], '保留')

    def test_preview_token_rejects_changed_samples_and_exclusion(self):
        effective = self.save_rule()['effective_at']
        self.trip('new', effective + 1000, (31.2, 121.4), (31.21, 121.41))
        preview = self.preview()
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE observations SET location=?', (json.dumps(dict(latitude=32, longitude=120, trusted=True, plottable=True, coordinate_system='WGS84（社区解释）')),))
        with self.assertRaisesRegex(ValueError, '变化'):
            self.apply(preview)
        with self.tags.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM commute_decisions').fetchone()[0], 0)

    def test_reassessment_preserves_exclusion_even_after_unmatched_then_matched(self):
        effective = self.save_rule()['effective_at']
        self.trip('new', effective + 1000, (31.2, 121.4), (31.21, 121.41))
        self.tags.query('owner', 'car', '2026-09-28')
        self.tags.update('owner', 'car', dict(action='commute-exclude', event_id='new'))
        preview = self.preview()
        self.assertEqual(preview['counts']['excluded'], 1)
        self.apply(preview)
        row = self.tags.query('owner', 'car', '2026-09-28')['events'][0]
        self.assertFalse(row['automatic_commute'])
        self.assertTrue(row['commute_excluded'])

    def test_apply_guard_failure_rolls_back_all_decisions(self):
        self.save_rule()
        self.trip('a', self.start + 1000, (31.2, 121.4), (31.21, 121.41))
        self.trip('b', self.start + 2000000, (31.21, 121.41), (31.2, 121.4))
        preview = self.preview()
        def guard():
            raise ValueError('changed account')
        with self.assertRaisesRegex(ValueError, 'changed account'):
            self.tags.update('owner', 'car', dict(action='commute-apply', date='2026-09-28', revision=1, token=preview['token']), guard=guard)
        with self.tags.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM commute_decisions').fetchone()[0], 0)

    def test_recent_collection_tags_without_opening_month(self):
        effective = self.save_rule()['effective_at']
        self.trip('recent', effective + 1000, (31.2, 121.4), (31.21, 121.41))
        self.tags.commute.collect('owner', 'car', effective + 1201000)
        with self.tags.store.connect() as db:
            self.assertEqual(db.execute('SELECT result FROM commute_decisions').fetchone()[0], 'matched')
        self.assertEqual(self.tags.commute.rule('other', 'car')['revision'], 0)

    def test_preview_without_rule_fails_cleanly_without_creating_database(self):
        with self.assertRaisesRegex(ValueError, '通勤规则'):
            self.tags.update('owner', 'car', dict(action='commute-preview', date='2026-09-28', revision=0))
        self.assertFalse(self.tags.store.path.exists())

    def test_preview_rejects_rule_change_and_exclusion_change(self):
        effective = self.save_rule()['effective_at']
        self.trip('new', effective + 1000, (31.2, 121.4), (31.21, 121.41))
        self.tags.query('owner', 'car', '2026-09-28')
        preview = self.preview()
        self.tags.update('owner', 'car', dict(action='commute-exclude', event_id='new'))
        with self.assertRaisesRegex(ValueError, '变化'):
            self.apply(preview)
        self.tags.update('owner', 'car', dict(action='commute-pause', revision=1))
        with self.assertRaisesRegex(ValueError, '通勤规则'):
            self.apply(preview)

    def test_outside_evidence_retry_can_match_corrected_endpoint(self):
        effective = self.save_rule()['effective_at']
        self.trip('outside', effective + 1000, (31.2, 121.4), (31.25, 121.41))
        row = self.tags.query('owner', 'car', '2026-09-28')['events'][0]
        self.assertEqual(row['commute_reason'], 'outside')
        with sqlite3.connect(self.db) as db:
            location = json.loads(db.execute("SELECT location FROM observations WHERE cache_key='outside-1'").fetchone()[0])
            location['latitude'] = 31.21
            db.execute("UPDATE observations SET location=? WHERE cache_key='outside-1'", (json.dumps(location),))
        self.assertTrue(self.tags.query('owner', 'car', '2026-09-28')['events'][0]['automatic_commute'])

    def test_reassessment_can_remove_automatic_label_without_removing_manual_commute(self):
        effective = self.save_rule()['effective_at']
        self.trip('new', effective + 1000, (31.2, 121.4), (31.21, 121.41))
        self.tags.query('owner', 'car', '2026-09-28')
        self.tags.update('owner', 'car', dict(action='save', event_id='new', tags=['通勤', '接娃'], note='保留', revision=0))
        self.tags.update('owner', 'car', dict(action='commute-save', revision=1,
            home=dict(latitude=32, longitude=120, radius_m=300), work=dict(latitude=32.1, longitude=120.1, radius_m=300)))
        payload = dict(action='commute-preview', date='2026-09-28', revision=2)
        preview = self.tags.update('owner', 'car', payload)
        self.assertEqual(preview['counts']['remove'], 1)
        self.tags.update('owner', 'car', dict(payload, action='commute-apply', token=preview['token']))
        row = self.tags.query('owner', 'car', '2026-09-28')['events'][0]
        self.assertFalse(row['automatic_commute'])
        self.assertEqual(row['tags'], ['通勤', '接娃'])
        self.assertEqual(row['note'], '保留')

    def test_exclusion_survives_outside_reassessment_and_can_be_cleared(self):
        effective = self.save_rule()['effective_at']
        self.trip('new', effective + 1000, (31.2, 121.4), (31.21, 121.41))
        self.tags.query('owner', 'car', '2026-09-28')
        self.tags.update('owner', 'car', dict(action='commute-exclude', event_id='new'))
        with sqlite3.connect(self.db) as db:
            encoded = db.execute("SELECT location FROM observations WHERE cache_key='new-1'").fetchone()[0]
            location = json.loads(encoded);location['latitude'] = 31.25
            db.execute("UPDATE observations SET location=? WHERE cache_key='new-1'", (json.dumps(location),))
        self.apply(self.preview())
        self.assertTrue(self.tags.query('owner', 'car', '2026-09-28')['events'][0]['commute_excluded'])
        self.tags.update('owner', 'car', dict(action='commute-include', event_id='new'))
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE observations SET location=? WHERE cache_key='new-1'", (encoded,))
        self.assertTrue(self.tags.query('owner', 'car', '2026-09-28')['events'][0]['automatic_commute'])

    def test_old_matched_decision_stays_readable_without_evidence_table(self):
        effective = self.save_rule()['effective_at']
        self.trip('old', effective + 1000, (31.2, 121.4), (31.21, 121.41))
        self.tags.query('owner', 'car', '2026-09-28')
        with self.tags.store.connect(write=True) as db, db:
            db.execute('DROP TABLE commute_evidence')
        row = self.tags.query('owner', 'car', '2026-09-28')['events'][0]
        self.assertTrue(row['automatic_commute'])
        self.assertTrue(row['commute_evidence']['legacy'])
        self.assertIsNone(row['commute_evidence']['direction'])
