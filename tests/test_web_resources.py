"""Bound memory and database lifetimes without caching stale vehicle data."""
import json
from pathlib import Path
import sqlite3
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

from zeekr_control.charging_analytics import ChargingAnalytics
from zeekr_control.events import EventStore
from zeekr_control.monitor import Monitor
from zeekr_control.snapshots import SnapshotStore


class WebResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'tracks.sqlite3'
        self.monitor = Monitor(self.path)

    def test_latest_and_first_page_memory_do_not_scale_with_event_payload_history(self):
        summary = json.dumps({'end_time': 1704126600000, 'private': 'x' * 4096})
        with self.monitor.tracks.connect() as db:
            db.executemany('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) '
                           'VALUES (?,?,?,?,?,?)',
                           ((str(i), 'car', 'trip_end', summary, 'private', i) for i in range(1500)))
        store = EventStore(self.path)
        for name, call in (
                ('latest', lambda: store.latest('car')),
                ('page', lambda: store.query('car', '2024-01-02', 'trip_end'))):
            with self.subTest(query=name):
                tracemalloc.start()
                try:
                    result = call()
                    _, peak = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
                self.assertLess(peak, 1024 * 1024, 'A small result must not load the full event history')
                self.assertNotIn('private', json.dumps(result))

    def test_old_charging_statistics_do_not_load_all_private_history(self):
        summary = json.dumps({'end_time': 1704126600000, 'private': 'x' * 4096})
        with self.monitor.tracks.connect() as db:
            db.executemany('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) '
                           'VALUES (?,?,?,?,?,?)',
                           ((str(i), 'car', 'charge_end', summary, 'private', i) for i in range(1500)))
        tracemalloc.start()
        try:
            result = ChargingAnalytics(self.path).statistics('car', 7, 'all', now=1711902600000)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1024 * 1024)
        self.assertEqual(result['records'], [])

    def test_charging_series_does_not_keep_raw_and_decoded_payload_copies(self):
        start = 1704067200000
        with self.monitor.tracks.connect() as db:
            state = {'charge': {'report_start': {'state_time': start},
                                'samples': [{'state_time': start + 1499 * 60000}]}}
            db.execute('INSERT INTO monitor_state VALUES (?,?)', ('car', json.dumps(state)))
            db.executemany('INSERT INTO report_observations VALUES (?,?,?,?,?)', (
                ('car', start + i * 60000, start + i * 60000,
                 json.dumps({'state_time': start + i * 60000, 'observed_at': start + i * 60000,
                             'soc': 50, 'power_kw': 6, 'charging': True, 'charging_mode': 'ac',
                             'private': 'x' * 4096}), 'synthetic') for i in range(1500)))
        tracemalloc.start()
        try:
            result = ChargingAnalytics(self.path).series('car', 'current', 'power-soc')
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 2 * 1024 * 1024)
        self.assertEqual(result['raw_count'], 1500)
        self.assertLessEqual(result['display_count'], 600)
        self.assertNotIn('private', json.dumps(result))

    def test_latest_skips_invalid_summaries_and_preserves_tie_order(self):
        with self.monitor.tracks.connect() as db:
            db.executemany('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) '
                           'VALUES (?,?,?,?,?,?)', [
                               ('old', 'car', 'trip_end', '{"distance_km": 1}', '', 1),
                               ('a', 'car', 'trip_end', '{"distance_km": 2}', '', 2),
                               ('b', 'car', 'trip_end', '{"distance_km": 3}', '', 2),
                               ('bad', 'car', 'trip_end', 'invalid', '', 3),
                               ('scalar', 'car', 'trip_end', 'null', '', 4),
                               ('other', 'other-car', 'charge_end', '{}', '', 5)])
        result = EventStore(self.path).latest('car')
        self.assertEqual(result['trip_end']['id'], 'b')
        self.assertEqual(result['trip_end']['distance_km'], 3)
        self.assertIsNone(result['charge_end'])

    def test_snapshot_unchanged_revision_does_not_decode_payload(self):
        store = SnapshotStore(self.root / 'snapshots.sqlite3')
        store.publish('scope', 'car', {'updateTime': 100, 'value': 1}, 100)
        with patch('zeekr_control.snapshots.json.loads', side_effect=AssertionError('unchanged payload decoded')):
            self.assertIsNone(store.read('scope', 'car', known_revision=1))
        store.publish('scope', 'car', {'updateTime': 100, 'value': 2}, 101)
        self.assertEqual(store.read('scope', 'car', known_revision=1)['raw']['value'], 2)
        store.publish('other-scope', 'car', {'updateTime': 100, 'value': 3}, 102)
        self.assertEqual(store.read('other-scope', 'car')['raw']['value'], 3)

    def test_snapshot_and_charging_connections_close_without_garbage_collection(self):
        connections = []
        original = sqlite3.connect

        def connect(*args, **kwargs):
            db = original(*args, **kwargs)
            connections.append(db)
            return db

        store = SnapshotStore(self.root / 'snapshots.sqlite3')
        analytics = ChargingAnalytics(self.path)
        with patch('sqlite3.connect', side_effect=connect):
            store.publish('scope', 'car', {'updateTime': 100}, 100)
            store.read('scope', 'car')
            analytics.process('car', 'current', 'power-soc')
            analytics.statistics('car', 7, 'all')
            with self.assertRaises(ValueError):
                analytics.session('car', 'invalid id')
        try:
            for db in connections:
                with self.assertRaises(sqlite3.ProgrammingError, msg='connection remains open after request'):
                    db.execute('SELECT 1')
        finally:
            for db in connections:
                db.close()

    def test_snapshot_read_does_not_initialize_storage_or_follow_symlink(self):
        path = self.root / 'snapshots.sqlite3'
        store = SnapshotStore(path)
        self.assertIsNone(store.read('scope', 'car'))
        self.assertFalse(path.exists())
        sqlite3.connect(path).close()
        self.assertIsNone(store.read('scope', 'car'))
        db = sqlite3.connect(path)
        try:
            self.assertEqual(db.execute('SELECT name FROM sqlite_master').fetchall(), [])
        finally:
            db.close()
        store.publish('scope', 'car', {'updateTime': 100}, 100)
        link = self.root / 'linked.sqlite3'
        link.symlink_to(path)
        with self.assertRaises(OSError):
            SnapshotStore(link).read('scope', 'car')
