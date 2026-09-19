from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.snapshots import SnapshotStore


def ms(iso):
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)


class SnapshotArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = SnapshotStore(self.root / 'snapshots.sqlite3')
        self.now = ms('2026-09-19T12:00:00')

    def database(self, year='2026', month='09'):
        return self.root / 'snapshot-archive' / year / (month + '.sqlite3')

    def rows(self, sql, path=None):
        db = sqlite3.connect(path or self.database())
        try:
            return db.execute(sql).fetchall()
        finally:
            db.close()

    def test_full_payload_roundtrips_and_files_are_private(self):
        raw = {'updateTime': str(self.now), 'nested': {'未知字段': [None, True, 12.5, '0']}}
        self.store.publish('scope', 'vehicle', raw, self.now, fetched_at=self.now - 1000)
        blob = self.rows('SELECT compressed_json FROM payloads')[0][0]
        self.assertEqual(json.loads(gzip.decompress(blob)), raw)
        row = self.rows('SELECT state_time,fetched_at,observed_at FROM reads')[0]
        self.assertEqual(row, (self.now, self.now - 1000, self.now))
        for path, mode in ((self.database(), 0o600), (self.database().parent, 0o700),
                           (self.database().parent.parent, 0o700)):
            self.assertEqual(path.stat().st_mode & 0o777, mode)

    def test_repeated_cache_keeps_read_times_but_deduplicates_payload(self):
        raw = {'updateTime': self.now, 'value': 1}
        for offset in (0, 60000, 60000):
            self.store.publish('scope', 'vehicle', raw, self.now + offset, fetched_at=self.now)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM payloads')[0][0], 1)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM reads')[0][0], 2)

    def test_corrections_old_and_unknown_time_are_archived_without_regressing_latest(self):
        for i, raw in enumerate(({'updateTime': self.now, 'value': 1},
                                 {'updateTime': self.now, 'value': 2},
                                 {'updateTime': self.now - 1000, 'value': 3}, {'value': 4})):
            self.store.publish('scope', 'vehicle', raw, self.now + i)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM reads')[0][0], 4)
        self.assertEqual(self.store.read('scope', 'vehicle')['raw']['value'], 2)

    def test_beijing_year_rollover_uses_observation_time_and_keeps_old_year(self):
        times = (ms('2026-12-31T15:59:59'), ms('2026-12-31T16:00:00'))
        for now in times:
            self.store.publish('scope', 'vehicle', {'updateTime': self.now}, now)
        for year, month in (('2026', '12'), ('2027', '01')):
            self.assertEqual(self.rows('SELECT COUNT(*) FROM reads', self.database(year, month))[0][0], 1)
        self.assertFalse(self.database('2026', '09').exists(), 'old vehicle time must not choose archive year')

    def test_vehicle_scope_and_source_are_kept_separate(self):
        for scope, vehicle, source in (('a', 'v1', 'monitor'), ('a', 'v2', 'monitor'),
                                        ('b', 'v1', 'monitor'), ('a', 'v1', 'manual')):
            self.store.publish(scope, vehicle, {'updateTime': self.now}, self.now, source=source)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM reads')[0][0], 4)

    def test_read_only_latest_does_not_archive(self):
        self.store.publish('scope', 'vehicle', {'value': 1}, self.now)
        for _ in range(3):
            self.store.read('scope', 'vehicle')
        self.assertEqual(self.rows('SELECT COUNT(*) FROM reads')[0][0], 1)

    def test_failed_archive_does_not_publish_latest(self):
        from zeekr_control.snapshot_archive import SnapshotArchive
        self.store.publish('scope', 'vehicle', {'value': 1}, self.now)
        with patch.object(SnapshotArchive, 'append', side_effect=OSError('synthetic disk full')):
            with self.assertRaises(OSError):
                self.store.publish('scope', 'vehicle', {'value': 2}, self.now + 1)
        self.assertEqual(self.store.read('scope', 'vehicle')['raw']['value'], 1)

    def test_transaction_failure_leaves_no_orphan_payload(self):
        self.store.publish('scope', 'vehicle', {'value': 1}, self.now)
        with sqlite3.connect(self.database()) as db:
            db.execute("CREATE TRIGGER fail_read BEFORE INSERT ON reads BEGIN SELECT RAISE(ABORT,'synthetic full'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.publish('scope', 'vehicle', {'value': 2}, self.now + 1)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM payloads')[0][0], 1)

    def test_concurrent_writers_are_idempotent(self):
        def publish(_):
            SnapshotStore(self.store.path).publish('scope', 'vehicle', {'value': 1}, self.now)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(publish, range(8)))
        self.assertEqual(self.rows('SELECT COUNT(*) FROM reads')[0][0], 1)
        self.assertEqual(self.rows('PRAGMA integrity_check')[0][0], 'ok')

    def test_rejects_symlink_directory_and_insecure_file(self):
        target = self.root / 'target'
        target.mkdir()
        archive = self.root / 'snapshot-archive'
        archive.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            self.store.publish('scope', 'vehicle', {}, self.now)
        archive.unlink()
        self.store.publish('scope', 'vehicle', {}, self.now)
        self.database().chmod(0o644)
        with self.assertRaises(OSError):
            self.store.publish('scope', 'vehicle', {}, self.now + 1)

    def test_invalid_capture_metadata_does_not_create_archive(self):
        for observed, fetched in ((True, 0), (-1, 0), (0, float('inf'))):
            with self.assertRaises(ValueError):
                self.store.publish('scope', 'vehicle', {}, observed, fetched_at=fetched)
        self.assertFalse((self.root / 'snapshot-archive').exists())

    def test_manual_refresh_archives_but_page_reads_do_not(self):
        from zeekr_control.web import App
        from zeekr_control.storage import save
        class Client:
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin): return {'updateTime': 1704067200000, 'extra': [1, None]}
        private = self.root / 'manual'
        save(private / 'session.json', {'accessToken': 'synthetic'})
        app = App(private / 'session.json', private / 'tracks.sqlite3', Client)
        self.addCleanup(app.close)
        app.refresh(1)
        app.state()
        app.state()
        path = next((private / 'snapshot-archive').glob('*/*.sqlite3'))
        self.assertEqual(self.rows('SELECT source,COUNT(*) FROM reads GROUP BY source', path),
                         [('manual', 1)])

    def test_future_schema_is_rejected_without_overwrite(self):
        self.store.publish('scope', 'vehicle', {'value': 1}, self.now)
        with sqlite3.connect(self.database()) as db:
            db.execute('PRAGMA user_version=99')
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.publish('scope', 'vehicle', {'value': 2}, self.now + 1)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM reads')[0][0], 1)
        self.assertEqual(self.rows('PRAGMA user_version')[0][0], 99)
