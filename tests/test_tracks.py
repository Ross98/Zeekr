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
        self.assertTrue(self.store.record('car-a', self.sample(1704067500000), 1704067531395, 900))
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
