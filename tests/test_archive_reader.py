import gzip
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from zeekr_control.snapshot_archive import SnapshotArchive
from zeekr_control.tracks import day_bounds
from zeekr_control.archive_reader import ArchiveReader


class ArchiveReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private' / 'snapshot-archive'
        self.writer = SnapshotArchive(self.root)
        self.reader = ArchiveReader(self.root)
        self.start, _ = day_bounds('2026-09-20')

    def append(self, offset=0, soc=70, state_offset=None, scope='owner', vehicle='car', extra=None):
        now = self.start + offset
        raw = {'updateTime': self.start + (offset if state_offset is None else state_offset),
               'vin': 'PRIVATE-VIN', 'accessToken': 'PRIVATE-TOKEN',
               'position': {'latitude': 111600000, 'longitude': 435600000},
               'additionalVehicleStatus': {'electricVehicleStatus': {'chargeLevel': soc},
                                           'climateStatus': {'interiorTemp': 25}}}
        if extra:
            raw.update(extra)
        self.writer.append(scope, vehicle, json.dumps(raw), raw.get('updateTime'), now, now, 'monitor')
        return raw

    def test_empty_read_does_not_create_directories(self):
        result = self.reader.timeline('owner', 'car', '2026-09-20')
        self.assertEqual(result['items'], [])
        self.assertIsNone(result['next_cursor'])
        self.assertFalse(self.root.exists())

    def test_paging_same_millisecond_is_lossless_and_scoped(self):
        self.append(soc=70)
        self.append(soc=71)
        self.append(60000, soc=72)
        self.append(60000, scope='different', soc=99)
        self.append(60000, vehicle='different', soc=98)
        page1 = self.reader.timeline('owner', 'car', '2026-09-20', limit=1)
        page2 = self.reader.timeline('owner', 'car', '2026-09-20', page1['next_cursor'], limit=1)
        page3 = self.reader.timeline('owner', 'car', '2026-09-20', page2['next_cursor'], limit=1)
        self.assertEqual(len({p['items'][0]['key'] for p in (page1, page2, page3)}), 3)
        self.assertEqual(page2['items'][0]['change'], 'revision')
        self.assertIsNone(page3['next_cursor'])

    def test_repeat_revision_regression_stale_unknown_and_gap(self):
        self.append()
        self.append(60000, state_offset=0)
        self.append(120000, soc=69, state_offset=0)
        self.append(180000, state_offset=-60000)
        self.append(1800000, state_offset=0)
        self.append(1860000, extra={'updateTime': None})
        self.append(1920000, state_offset=2100000)
        rows = self.reader.timeline('owner', 'car', '2026-09-20')['items']
        self.assertEqual([r['change'] for r in rows[:4]], ['first', 'repeat', 'revision', 'regression'])
        self.assertIn('stale', rows[4]['flags'])
        self.assertEqual(rows[4]['gap_seconds'], 1620)
        self.assertIn('unknown_time', rows[5]['flags'])
        self.assertIn('future_time', rows[6]['flags'])

    def test_previous_month_supplies_boundary_context(self):
        self.start, _ = day_bounds('2026-10-01')
        self.append(-60000)
        self.append(0, state_offset=-60000)
        rows = self.reader.timeline('owner', 'car', '2026-10-01')['items']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['change'], 'repeat')

    def test_detail_and_comparison_are_allowlisted_and_include_missing_changes(self):
        self.append()
        self.append(60000, soc=67, extra={'additionalVehicleStatus': {
            'electricVehicleStatus': {'chargeLevel': 67}, 'unknown': {'secret': 'PRIVATE-UNKNOWN'}}})
        rows = self.reader.timeline('owner', 'car', '2026-09-20')['items']
        result = self.reader.snapshot('owner', 'car', rows[0]['key'])
        self.assertEqual(result['summary']['battery'], '70%')
        timestamp = next(field for field in result['fields'] if field['path'] == 'updateTime')
        self.assertEqual(timestamp['status'], 'known')
        self.assertIn('2026-09-20', timestamp['value'])
        comparison = self.reader.compare('owner', 'car', rows[0]['key'], rows[1]['key'])
        paths = {r['path']: r for r in comparison['changes']}
        soc = paths['additionalVehicleStatus.electricVehicleStatus.chargeLevel']
        self.assertEqual(soc['before']['raw'], '70')
        self.assertEqual(soc['after']['raw'], '67')
        self.assertEqual(paths['additionalVehicleStatus.climateStatus.interiorTemp']['after']['status'], 'missing')
        encoded = json.dumps([result, comparison, rows])
        for private in ('PRIVATE-', 'latitude', 'longitude', '111600000', 'scope_key', 'digest', 'compressed_json'):
            self.assertNotIn(private, encoded)

    def test_selection_cannot_cross_vehicle_or_account(self):
        self.append()
        key = self.reader.timeline('owner', 'car', '2026-09-20')['items'][0]['key']
        for scope, vehicle in [('owner', 'different'), ('different', 'car'), (None, 'car')]:
            with self.assertRaises(ValueError):
                self.reader.snapshot(scope, vehicle, key)

    def test_validate_dates_selection_cursor_and_page_size(self):
        for date in ('', '2026-9-20', '2026-02-30', '../2026'):
            with self.assertRaises(ValueError):
                self.reader.timeline('owner', 'car', date)
        for limit in (0, 501, True, 1.5):
            with self.assertRaises(ValueError):
                self.reader.timeline('owner', 'car', '2026-09-20', limit=limit)
        for key in ('../../session.json', '202613.1', '202609.-1', '202609.1?mode=rw'):
            with self.assertRaises(ValueError):
                self.reader.snapshot('owner', 'car', key)
        self.append()
        for cursor in ('garbage', '0:0', str(self.start) + ':999'):
            with self.assertRaises(ValueError):
                self.reader.timeline('owner', 'car', '2026-09-20', cursor)

    def test_readonly_does_not_modify_archive(self):
        self.append()
        shard = self.root / '2026' / '09.sqlite3'
        original = shard.read_bytes(), shard.stat().st_mtime_ns
        listing = self.reader.timeline('owner', 'car', '2026-09-20')
        self.reader.snapshot('owner', 'car', listing['items'][0]['key'])
        self.assertEqual((shard.read_bytes(), shard.stat().st_mtime_ns), original)

    def test_symlink_and_insecure_permissions_rejected(self):
        self.append()
        shard = self.root / '2026' / '09.sqlite3'
        os.chmod(shard, 0o644)
        with self.assertRaises(OSError):
            self.reader.timeline('owner', 'car', '2026-09-20')
        os.chmod(shard, 0o600)
        original = shard.with_suffix('.original')
        shard.rename(original)
        shard.symlink_to(original)
        with self.assertRaises(OSError):
            self.reader.timeline('owner', 'car', '2026-09-20')

    def test_unsupported_or_corrupt_payload_rejected(self):
        self.append()
        key = self.reader.timeline('owner', 'car', '2026-09-20')['items'][0]['key']
        with sqlite3.connect(self.root / '2026' / '09.sqlite3') as db:
            db.execute('UPDATE payloads SET compressed_json=?', (gzip.compress(b'{}'),))
        with self.assertRaises(ValueError):
            self.reader.snapshot('owner', 'car', key)

    def test_decompression_is_bounded_even_if_declared_size_is_small(self):
        self.append()
        key = self.reader.timeline('owner', 'car', '2026-09-20')['items'][0]['key']
        from zeekr_control.archive_reader import MAX_PAYLOAD_BYTES
        with sqlite3.connect(self.root / '2026' / '09.sqlite3') as db:
            db.execute('UPDATE payloads SET compressed_json=?,raw_bytes=2',
                       (gzip.compress(b' ' * (MAX_PAYLOAD_BYTES + 1)),))
        with self.assertRaises(ValueError):
            self.reader.snapshot('owner', 'car', key)

    def test_comparison_detects_changes_beyond_truncated_display(self):
        self.append(extra={'temStatus': {'swVersion': 'x' * 130 + 'A'}})
        self.append(60000, extra={'temStatus': {'swVersion': 'x' * 130 + 'B'}})
        rows = self.reader.timeline('owner', 'car', '2026-09-20')['items']
        compared = self.reader.compare('owner', 'car', rows[0]['key'], rows[1]['key'])
        self.assertIn('temStatus.swVersion', [row['path'] for row in compared['changes']])

    def test_record_identifier_overflow_is_validation_error(self):
        self.append()
        with self.assertRaises(ValueError):
            self.reader.snapshot('owner', 'car', '202609.9999999999999999999')

    def test_stream_is_scoped_cross_month_and_bounded(self):
        self.start, _ = day_bounds('2026-10-01')
        self.append(-60000)
        self.append(0, soc=69)
        self.append(0, scope='different', soc=99)
        rows = list(self.reader.iter_records('owner', 'car', self.start-60000, self.start+60000))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0]['change'], 'new')
        self.assertNotEqual(rows[0][0]['key'].split('.')[0], rows[1][0]['key'].split('.')[0])
        with self.assertRaises(ValueError):
            list(self.reader.iter_records('owner', 'car', self.start-60000, self.start+60000, limit=1))

    def test_old_fetch_republished_later_is_stale_at_observation_time(self):
        raw = self.append()
        self.writer.append('owner', 'car', json.dumps(raw), self.start,
                           self.start+3600000, self.start, 'manual')
        rows = self.reader.timeline('owner', 'car', '2026-09-20')['items']
        self.assertIn('stale', rows[1]['flags'])

    def test_analytics_yield_does_not_hold_a_lock_blocking_archive_writes(self):
        self.append()
        stream = self.reader.iter_records('owner', 'car', self.start, self.start+86400000)
        next(stream)
        try:
            self.append(60000, soc=69)
            self.assertEqual(len(self.reader.timeline('owner', 'car', '2026-09-20')['items']), 2)
        finally:
            stream.close()


if __name__ == '__main__':
    unittest.main()
