"""Offline tests: identifiers and observations are synthetic, never owner records."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


class TrackTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('zeekr_control.tracks'), '轨迹存储尚未实现')
        from zeekr_control.tracks import TrackStore
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TrackStore(Path(self.temp.name) / 'private' / 'tracks.sqlite3')

    def sample(self, timestamp=1704067200000, trusted=True, latitude=111600000):
        return {'updateTime': timestamp, 'position': {'latitude': latitude, 'longitude': 435600000,
                    'marsCoordinates': False, 'posCanBeTrusted': trusted}}

    def test_repeated_cache_is_not_new_point_but_new_time_same_position_is(self):
        self.assertTrue(self.store.record('car-a', self.sample(), 1704067231395, 900))
        self.assertFalse(self.store.record('car-a', self.sample(), 1704067331395, 900))
        self.assertTrue(self.store.record('car-a', self.sample(1704067260000), 1704067291395, 900))
        result = self.store.day('car-a', '2024-01-01')
        self.assertEqual(len(result['observations']), 2)
        self.assertEqual(len(result['segments'][0]), 2)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.path.parent.stat().st_mode & 0o777, 0o700)

    def test_untrusted_observation_and_long_gap_split_route(self):
        for timestamp, trusted in ((1704067200000, True), (1704067500000, False),
                                   (1704067800000, True), (1704071400000, True)):
            self.store.record('car-a', self.sample(timestamp, trusted), timestamp, 900)
        result = self.store.day('car-a', '2024-01-01')
        self.assertEqual([len(x) for x in result['segments']], [1, 1, 1])
        self.assertEqual(len(self.store.day('car-b', '2024-01-01')['observations']), 0)

    def test_missing_timestamp_does_not_become_timed_route(self):
        self.store.record('car-a', self.sample(None), 1704067231395, 900)
        result = self.store.day('car-a', '2024-01-01')
        self.assertEqual(len(result['observations']), 1)
        self.assertEqual(result['segments'], [])

    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):
            self.store.day('car-a', '../../etc')

    def test_connection_closed_after_transaction(self):
        import sqlite3
        with self.store.connect() as connection:
            connection.execute('SELECT 1')
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')

    def test_recorded_vehicle_can_be_found_after_restart(self):
        from zeekr_control.tracks import TrackStore
        self.store.record('car-a', self.sample(), 1704067231395, 900)
        reopened = TrackStore(self.store.path)
        self.assertEqual(reopened.vehicles(), [{'key': 'car-a', 'label': '本地车辆 1'}])
        self.assertEqual(reopened.day('car-a', '2024-01-01')['count'], 1)

    def test_gap_quality_explains_unknown_untrusted_and_long_interval(self):
        base = 1704067200000
        records = [(base, True, base), (base + 60000, False, base + 60000),
                   (base + 120000, True, base + 120000), (None, True, base + 180000),
                   (base + 240000, True, base + 240000), (base + 600000, True, base + 600000)]
        for timestamp, trusted, observed in records:
            self.store.record('car-a', self.sample(timestamp, trusted), observed, 900)
        result = self.store.day('car-a', '2024-01-01')
        self.assertEqual([len(x) for x in result['segments']], [1, 1, 1, 1])
        self.assertIn('gaps', result)
        self.assertTrue(any('不可信' in gap['reason'] for gap in result['gaps']))
        self.assertTrue(any('时间缺失' in gap['reason'] and gap['duration_seconds'] is None
                            for gap in result['gaps']))
        self.assertTrue(any(gap['duration_seconds'] == 360 for gap in result['gaps']))
        self.assertEqual(result['quality'], {'trusted_count': 5, 'untrusted_count': 1,
                         'unplottable_count': 0, 'gap_count': len(result['gaps']), 'segment_count': 4})

    def test_observed_gap_and_time_reversal_do_not_bridge(self):
        base = 1704067200000
        for timestamp, observed in [(base, base), (base + 60000, base + 300000),
                                    (base + 30000, base + 360000)]:
            self.store.record('car-a', self.sample(timestamp), observed, 180)
        result = self.store.day('car-a', '2024-01-01')
        self.assertEqual([len(x) for x in result['segments']], [1, 1, 1])
        self.assertIn('gaps', result)
        self.assertTrue(any('本机观测' in gap['reason'] for gap in result['gaps']))
        self.assertTrue(any('未递增' in gap['reason'] and gap['duration_seconds'] is None
                            for gap in result['gaps']))

    def test_unplottable_location_has_explainable_gap(self):
        self.store.record('car-a', self.sample(latitude=999999999999), 1704067200000, 180)
        result = self.store.day('car-a', '2024-01-01')
        self.assertIn('quality', result)
        self.assertEqual(result['quality']['unplottable_count'], 1)
        self.assertEqual(result['segments'], [])
        self.assertTrue(result['gaps'])

    def test_range_reports_meaningful_boundary_gaps_and_truthful_truncation(self):
        base = 1704067200000
        self.store.record('car-a', self.sample(base + 300000), base + 300000, 180)
        self.assertTrue(callable(getattr(self.store, 'between', None)), 'trip range query missing')
        result = self.store.between('car-a', base, base + 600000, '2024-01-01')
        self.assertEqual([gap['duration_seconds'] for gap in result['gaps']], [300, 300])
        self.assertEqual(self.store.day('car-a', '2024-01-01')['gaps'], [])
        with self.store.connect() as db:
            location = __import__('json').dumps({'trusted': True, 'plottable': True,
                                               'latitude': 31, 'longitude': 121})
            db.executemany('INSERT INTO observations (vehicle,cache_key,state_time,observed_time,gap_seconds,location) '
                           'VALUES (?,?,?,?,?,?)',
                           [('car-b', str(index), base + index, base + index, 180, location)
                            for index in range(5001)])
        limited = self.store.between('car-b', base, base + 600000, '2024-01-01')
        self.assertEqual(limited['count'], 5000)
        self.assertTrue(limited['truncated'])
        self.assertEqual(limited['gaps'], [])

    def test_readonly_track_query_creates_no_schema(self):
        import sqlite3
        path = self.store.path.with_name('empty.sqlite3')
        sqlite3.connect(path).close()
        path.chmod(0o600)
        before = path.read_bytes()
        from zeekr_control.tracks import TrackStore
        self.assertIn('readonly', __import__('inspect').signature(TrackStore).parameters,
                      'read-only track access missing')
        reader = TrackStore(path, readonly=True)
        self.assertEqual(reader.day('car-a', '2024-01-01')['count'], 0)
        self.assertEqual(before, path.read_bytes())

    def test_reordered_points_do_not_invent_missing_trip_boundaries(self):
        base = 1704067200000
        self.store.record('car-a', self.sample(base + 600000), base + 600000, 180)
        self.store.record('car-a', self.sample(base), base + 660000, 180)
        result = self.store.between('car-a', base, base + 600000, '2024-01-01')
        self.assertEqual(len(result['gaps']), 1)
        self.assertIn('未递增', result['gaps'][0]['reason'])
