import tempfile
from pathlib import Path
import unittest


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_newer_snapshot_wins_and_same_time_can_be_revised(self):
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name) / 'snapshots.sqlite3')
        first = store.publish('scope-a', 'vehicle-a', {'updateTime': 200, 'value': 1}, 300)
        self.assertEqual(first['revision'], 1)
        self.assertFalse(store.publish('scope-a', 'vehicle-a', {'updateTime': 100, 'value': 0}, 400)['changed'])
        revised = store.publish('scope-a', 'vehicle-a', {'updateTime': 200, 'value': 2}, 500)
        self.assertTrue(revised['changed'])
        self.assertEqual(revised['revision'], 2)
        self.assertEqual(store.read('scope-a', 'vehicle-a')['raw']['value'], 2)

    def test_scope_and_vehicle_are_isolated_and_invalid_time_cannot_replace_valid(self):
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name) / 'snapshots.sqlite3')
        store.publish('scope-a', 'vehicle-a', {'updateTime': 200, 'value': 'kept'}, 300)
        self.assertFalse(store.publish('scope-a', 'vehicle-a', {'value': 'missing-time'}, 400)['changed'])
        self.assertIsNone(store.read('scope-b', 'vehicle-a'))
        self.assertIsNone(store.read('scope-a', 'vehicle-b'))
        self.assertEqual(store.read('scope-a', 'vehicle-a')['raw']['value'], 'kept')

    def test_first_snapshot_without_time_is_readable_but_marked_unknown(self):
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name) / 'snapshots.sqlite3')
        result = store.publish('scope-a', 'vehicle-a', {'value': 1}, 300, fetched_at=250)
        self.assertTrue(result['changed'])
        loaded = store.read('scope-a', 'vehicle-a')
        self.assertIsNone(loaded['state_time'])
        self.assertEqual(loaded['observed_at'], 300)
        self.assertEqual(loaded['fetched_at'], 250)
