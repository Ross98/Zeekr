import tempfile
from pathlib import Path
import unittest
from contextlib import closing


class SnapshotStoreTests(unittest.TestCase):
    def test_digit_like_invalid_vehicle_time_does_not_discard_other_evidence(self):
        from zeekr_control.snapshots import SnapshotStore,_time
        from zeekr_control.archive_reader import ArchiveReader
        store=SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        original={'updateTime':1000,'value':'accepted'}
        store.publish('scope','car',original,1100)
        for index,value in enumerate(('²','①','1²')):
            with self.subTest(value=value):
                self.assertIsNone(_time({'updateTime':value}))
                result=store.publish('scope','car',{'updateTime':value,'value':'retained evidence'},1200+index)
                self.assertEqual(result['change'],'time_unknown')
                self.assertFalse(result['changed'])
                self.assertEqual(store.read('scope','car')['raw'],original)
        rows=list(ArchiveReader(Path(self.temp.name)/'snapshot-archive').iter_metadata('scope','car',0,3000))
        self.assertEqual(len(rows),4,'unknown vehicle timestamps must not discard actual reads')
        self.assertEqual(_time({'updateTime':'1704067200000'}),1704067200000)
        self.assertEqual(_time({'updateTime':'١٠٠٠'}),1000)

    def test_invalid_snapshot_metadata_is_rejected_even_for_known_revision(self):
        import sqlite3
        from zeekr_control.snapshots import SnapshotStore
        store=SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        for column,value in (('state_time','broken'),('state_time',-1),('fetched_at','broken'),
                             ('observed_at',-1),('revision','broken'),('revision',0)):
            with self.subTest(column=column,value=value):
                with closing(store.connect()) as db,db:
                    db.execute('DELETE FROM snapshots')
                store.publish('scope','car',{'updateTime':1000},1100)
                with sqlite3.connect(store.path) as db:
                    db.execute('UPDATE snapshots SET '+column+'=?',(value,))
                before=store.path.read_bytes()
                for known in (None,1):
                    with self.assertRaises(OSError):store.read('scope','car',known_revision=known)
                self.assertEqual(store.path.read_bytes(),before)

    def test_corrupt_ordering_metadata_causes_controlled_publication_error(self):
        import sqlite3
        from zeekr_control.snapshots import SnapshotStore
        store=SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        for table,column in (('snapshots','state_time'),('snapshots','revision'),
                             ('snapshots','fetched_at'),('snapshot_publications','fetched_at')):
            with self.subTest(table=table,column=column):
                with closing(store.connect()) as db,db:
                    db.execute('DELETE FROM snapshots');db.execute('DELETE FROM snapshot_publications')
                store.publish('scope','car',{'updateTime':1000,'value':1},1100)
                with sqlite3.connect(store.path) as db:
                    db.execute('UPDATE '+table+' SET '+column+"='broken'")
                with self.assertRaises(OSError):
                    store.publish('scope','car',{'updateTime':1000,'value':2},1200)
                with sqlite3.connect(store.path) as db:
                    self.assertIn('"value":1',db.execute('SELECT raw FROM snapshots').fetchone()[0])

    def test_revision_exhaustion_preserves_latest_and_archives_actual_read(self):
        import sqlite3
        from zeekr_control.snapshots import SnapshotStore
        store=SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        store.publish('scope','car',{'updateTime':1000,'value':1},1100)
        with sqlite3.connect(store.path) as db:
            db.execute('UPDATE snapshots SET revision=?',(9223372036854775807,))
        self.assertEqual(store.read('scope','car')['revision'],9223372036854775807)
        with self.assertRaises(OSError):
            store.publish('scope','car',{'updateTime':1100,'value':2},1200)
        self.assertEqual(store.read('scope','car')['raw']['value'],1)
        with sqlite3.connect(store.path.parent/'snapshot-archive/1970/01.sqlite3') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reads').fetchone()[0],2)

    def test_bad_snapshot_payload_is_a_controlled_storage_error(self):
        import hashlib
        import sqlite3
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        store.publish('scope','car',{'value':1},1000)
        for encoded in ('not-json','[]','null','['*1200+'0'+']'*1200,'{"value":NaN}','{"value":1e999}'):
            with self.subTest(encoded=encoded[:30]):
                with sqlite3.connect(store.path) as db:
                    db.execute('UPDATE snapshots SET raw=?,digest=?',
                               (encoded,hashlib.sha256(encoded.encode()).hexdigest()))
                before = store.path.read_bytes()
                with self.assertRaises(OSError):store.read('scope','car')
                self.assertEqual(store.path.read_bytes(),before)

    def test_oversized_snapshot_is_rejected_before_json_decode(self):
        from unittest.mock import patch
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        store.publish('scope','car',{'padding':'x'*100},1000)
        with patch('zeekr_control.snapshots.MAX_PAYLOAD_BYTES',32):
            with patch('zeekr_control.snapshots.json.loads',side_effect=AssertionError('must not decode')):
                with self.assertRaises(OSError):store.read('scope','car')

    def test_valid_fetch_repairs_corrupted_payload_even_when_stored_digest_matches(self):
        import sqlite3
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        raw = {'updateTime':1000,'value':1}
        first = store.publish('scope','car',raw,1100)
        with sqlite3.connect(store.path) as db:
            db.execute("UPDATE snapshots SET raw='broken-json'")
        result = store.publish('scope','car',raw,1200)
        self.assertTrue(result['changed'])
        self.assertGreater(result['revision'],first['revision'])
        self.assertEqual(store.read('scope','car')['raw'],raw)
        self.assertEqual(store.read('scope','car',known_revision=first['revision'])['raw'],raw)

    def test_private_snapshot_writer_rejects_hardlink_before_modifying_other_database(self):
        import os
        import sqlite3
        from zeekr_control.snapshots import SnapshotStore
        root = Path(self.temp.name)
        other = root/'other.sqlite3'
        with sqlite3.connect(other) as db:
            db.execute('CREATE TABLE sentinel(value TEXT)')
        other.chmod(0o600)
        path = root/'snapshots.sqlite3'
        os.link(other,path)
        before = other.read_bytes()
        error = None
        try:
            SnapshotStore(path).publish('scope','car',{'value':1},1000,owner_key='owner')
        except OSError as caught:
            error = caught
        self.assertTrue(other.read_bytes()==before,'snapshot writer modified unrelated hardlinked database')
        self.assertIsInstance(error,OSError)
        path.unlink()
        store = SnapshotStore(path)
        store.publish('scope','car',{'value':2},1001,owner_key='owner')
        self.assertEqual(store.read('scope','car')['raw']['value'],2)
        self.assertTrue(other.read_bytes()==before)

    def test_private_snapshot_reader_rejects_hardlink(self):
        import os
        from zeekr_control.snapshots import SnapshotStore
        path = Path(self.temp.name)/'snapshots.sqlite3'
        store = SnapshotStore(path)
        store.publish('scope','car',{'value':1},1000)
        os.link(path,path.with_name('alias'))
        with self.assertRaises(OSError):
            store.read('scope','car')

    def test_private_snapshot_reader_and_writer_reject_permissive_file(self):
        from zeekr_control.snapshots import SnapshotStore
        path = Path(self.temp.name)/'snapshots.sqlite3'
        store = SnapshotStore(path)
        store.publish('scope','car',{'value':1},1000)
        path.chmod(0o644)
        for action in (lambda:store.read('scope','car'),lambda:store.bind_archive('scope','car','owner')):
            with self.subTest(action=action), self.assertRaises(OSError):
                action()
        self.assertEqual(path.stat().st_mode & 0o777,0o644)

    def test_private_snapshot_parent_and_broken_link_fail_before_sqlite(self):
        from unittest.mock import patch
        from zeekr_control.snapshots import SnapshotStore
        root = Path(self.temp.name)
        private = root/'private'
        private.mkdir(mode=0o700)
        store = SnapshotStore(private/'snapshots.sqlite3')
        store.publish('scope','car',{'value':1},1000)
        private.chmod(0o755)
        with patch('zeekr_control.snapshots.sqlite3.connect',side_effect=AssertionError('SQLite must not open')):
            for action in (lambda:store.read('scope','car'),lambda:store.bind_archive('scope','car','owner')):
                with self.assertRaises(OSError):action()
        self.assertEqual(private.stat().st_mode & 0o777,0o755)
        private.chmod(0o700)
        alias = root/'alias'
        alias.symlink_to(private,target_is_directory=True)
        broken = private/'broken.sqlite3'
        broken.symlink_to(private/'absent')
        with patch('zeekr_control.snapshots.sqlite3.connect',side_effect=AssertionError('SQLite must not open')):
            for candidate in (SnapshotStore(alias/'snapshots.sqlite3'),SnapshotStore(broken)):
                with self.assertRaises(OSError):candidate.read('scope','car')
                with self.assertRaises(OSError):candidate.connect()

    def test_late_publication_of_older_fetch_cannot_undo_same_time_revision(self):
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        store.publish('scope','car',{'updateTime':1000,'value':'newer-fetch'},1200,fetched_at=1200)
        result = store.publish('scope','car',{'updateTime':1000,'value':'older-fetch'},1300,fetched_at=1100)
        self.assertFalse(result['changed'])
        self.assertEqual(result['change'],'superseded')
        self.assertEqual(store.read('scope','car')['raw']['value'],'newer-fetch')
        import sqlite3
        with sqlite3.connect(Path(self.temp.name)/'snapshot-archive/1970/01.sqlite3') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reads').fetchone()[0],2)

    def test_repeat_advances_fetch_watermark_without_changing_payload_revision(self):
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        raw = {'updateTime':1000,'value':'kept'}
        first = store.publish('scope','car',raw,1100,fetched_at=1100)
        store.publish('scope','car',raw,1300,fetched_at=1300)
        result = store.publish('scope','car',{'updateTime':1000,'value':'obsolete'},1400,fetched_at=1200)
        self.assertFalse(result['changed'])
        self.assertEqual(store.read('scope','car')['raw'],raw)
        self.assertEqual(store.read('scope','car')['revision'],first['revision'])
        self.assertEqual(store.read('scope','car')['fetched_at'],1100)

    def test_legacy_snapshot_ordering_and_newer_vehicle_time_take_precedence(self):
        import sqlite3
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        store.publish('scope','car',{'updateTime':1000,'value':1},1200)
        with sqlite3.connect(store.path) as db:
            db.execute('DROP TABLE snapshot_publications')
        self.assertFalse(store.publish('scope','car',{'updateTime':1000,'value':0},1300,fetched_at=1100)['changed'])
        self.assertTrue(store.publish('scope','car',{'updateTime':1100,'value':2},1301,fetched_at=1100)['changed'])
        self.assertEqual(store.read('scope','car')['raw']['value'],2)

    def test_same_fetch_uses_observation_order_and_unknown_state_keeps_its_classification(self):
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        store.publish('scope','car',{'value':1},1300,fetched_at=1200)
        self.assertEqual(store.publish('scope','car',{'value':2},1250,fetched_at=1200)['change'],'superseded')
        self.assertEqual(store.publish('scope','car',{'value':1},1251,fetched_at=1200)['change'],'time_unknown')
        self.assertEqual(store.read('scope','car')['raw']['value'],1)

    def test_separate_writers_cannot_publish_older_fetch_after_newer_commit(self):
        import json
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from zeekr_control.snapshot_archive import SnapshotArchive
        from zeekr_control.snapshots import SnapshotStore
        path = Path(self.temp.name)/'snapshots.sqlite3'
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = SnapshotArchive.append
        def delayed(archive,*args,**kwargs):
            result = original(archive,*args,**kwargs)
            if json.loads(args[2]).get('value') == 'older':
                entered.set()
                if not release.wait(2):
                    raise RuntimeError('synthetic publication not released')
            return result
        with patch.object(SnapshotArchive,'append',new=delayed), ThreadPoolExecutor(max_workers=2) as pool:
            older = pool.submit(SnapshotStore(path).publish,'scope','car',
                                {'updateTime':1000,'value':'older'},1400,1100)
            self.assertTrue(entered.wait(1))
            newer = pool.submit(SnapshotStore(path).publish,'scope','car',
                                {'updateTime':1000,'value':'newer'},1300,1200)
            self.assertTrue(newer.result(timeout=2)['changed'])
            release.set()
            self.assertEqual(older.result(timeout=2)['change'],'superseded')
        self.assertEqual(SnapshotStore(path).read('scope','car')['raw']['value'],'newer')

    def test_failed_latest_transaction_rolls_back_watermark_and_retry_keeps_one_archived_read(self):
        import sqlite3
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        store.publish('scope','car',{'updateTime':1000,'value':1},1100)
        with sqlite3.connect(store.path) as db:
            db.execute("CREATE TRIGGER fail_latest BEFORE INSERT ON snapshots BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            store.publish('scope','car',{'updateTime':1000,'value':2},1200)
        with sqlite3.connect(store.path) as db:
            self.assertEqual(db.execute('SELECT fetched_at FROM snapshot_publications').fetchone()[0],1100)
            db.execute('DROP TRIGGER fail_latest')
        store.publish('scope','car',{'updateTime':1000,'value':2},1200)
        self.assertEqual(store.read('scope','car')['raw']['value'],2)
        with sqlite3.connect(Path(self.temp.name)/'snapshot-archive/1970/01.sqlite3') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reads').fetchone()[0],2)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_publish_classifies_time_and_full_payload_independently(self):
        from zeekr_control.snapshots import SnapshotStore
        store = SnapshotStore(Path(self.temp.name) / 'snapshots.sqlite3')
        cases = [({'updateTime': 200, 'value': 1}, 'new'),
                 ({'value': 1, 'updateTime': 200}, 'repeat'),
                 ({'updateTime': 200, 'value': 2}, 'revision'),
                 ({'updateTime': 300, 'value': 2}, 'new'),
                 ({'updateTime': 100, 'value': 3}, 'regression'),
                 ({'value': 3}, 'time_unknown')]
        for index, (raw, expected) in enumerate(cases):
            with self.subTest(expected=expected):
                result = store.publish('scope-a', 'vehicle-a', raw, 400 + index)
                self.assertEqual(result['change'], expected)
        self.assertEqual(store.read('scope-a', 'vehicle-a')['raw'], {'updateTime': 300, 'value': 2})

    def test_publication_links_same_account_history_without_sharing_live_snapshot(self):
        from zeekr_control.snapshots import SnapshotStore
        from zeekr_control.archive_reader import ArchiveReader
        store=SnapshotStore(Path(self.temp.name)/'snapshots.sqlite3')
        store.publish('old','car',{'updateTime':1000},1000,owner_key='account')
        store.publish('new','car',{'updateTime':2000},2000,owner_key='account')
        self.assertEqual(store.read('new','car')['raw'],{'updateTime':2000})
        self.assertEqual(store.read('old','car')['raw'],{'updateTime':1000})
        self.assertEqual(len(list(ArchiveReader(Path(self.temp.name)/'snapshot-archive').iter_metadata('new','car',0,3000))),2)

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
