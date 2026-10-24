"""SQLite metadata entry points must preserve locks on existing DB inodes."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.private_state import database
from zeekr_control.personal_store import PersonalStore
from zeekr_control.snapshots import SnapshotStore
from zeekr_control.system_notifications import AuthFailureAlert


class SQLiteFileBoundaryTests(unittest.TestCase):
    def factories(self, root):
        return [('metadata', root/'metadata.sqlite3', lambda: database(root/'metadata.sqlite3')),
                ('personal', root/'personal.sqlite3', lambda: PersonalStore(root/'personal.sqlite3').connect(write=True)),
                ('snapshots', root/'snapshots.sqlite3', lambda: closing(SnapshotStore(root/'snapshots.sqlite3').connect())),
                ('notifications', root/'system-notifications.sqlite3', lambda: AuthFailureAlert(root).connect())]

    def test_existing_database_entry_points_do_not_raw_open_its_inode(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for label,path,factory in self.factories(root):
                with self.subTest(store=label):
                    with factory() as db:
                        db.execute('CREATE TABLE sentinel(value TEXT)')
                        db.execute("INSERT INTO sentinel VALUES ('synthetic preserved record')")
                        db.commit()
                    raw_open=os.open
                    def guarded(candidate,*args,**kwargs):
                        if Path(candidate)==path:
                            raise AssertionError('raw open/close of existing SQLite inode may cancel reader locks')
                        return raw_open(candidate,*args,**kwargs)
                    with patch('os.open',side_effect=guarded),factory() as db:
                        self.assertEqual([tuple(row) for row in db.execute('SELECT value FROM sentinel')],[('synthetic preserved record',)])

    def test_unsafe_existing_targets_are_rejected_before_sqlite(self):
        with tempfile.TemporaryDirectory() as folder:
            for label,_,_ in self.factories(Path(folder)):
                for kind in ('directory','symlink','hardlink','public-mode'):
                    with self.subTest(store=label,target=kind):
                        root=Path(folder)/(label+'-'+kind);root.mkdir(mode=0o700)
                        _,path,factory=next(item for item in self.factories(root) if item[0]==label)
                        if kind=='directory':path.mkdir(mode=0o700)
                        elif kind=='symlink':path.symlink_to(root/'absent.sqlite3')
                        elif kind=='hardlink':
                            other=root/'other.sqlite3';other.touch(mode=0o600);os.link(other,path)
                        else:path.touch(mode=0o644);path.chmod(0o644)
                        with patch('sqlite3.connect',side_effect=AssertionError('unsafe target must never reach SQLite')):
                            with self.assertRaises(OSError):
                                with factory():pass


class AdditionalSQLiteEntryTests(unittest.TestCase):
    def test_query_reopen_preserves_reader_lock_against_another_process(self):
        import subprocess
        import sys
        from zeekr_control.query_policy import QueryPolicy
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'queries.sqlite3';policy=QueryPolicy(path)
            with closing(policy._connect()) as db:db.execute('CREATE TABLE sentinel(value TEXT)')
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as reader:
                reader.execute('BEGIN');reader.execute('SELECT * FROM sentinel').fetchall()
                with closing(policy._connect()):pass
                probe='''import sqlite3,sys
db=sqlite3.connect(sys.argv[1],timeout=0)
blocked=False
try:db.execute('BEGIN EXCLUSIVE')
except sqlite3.OperationalError as error:blocked='locked' in str(error)
finally:db.close()
raise SystemExit(0 if blocked else 2)
'''
                result=subprocess.run([sys.executable,'-c',probe,str(path)],capture_output=True,timeout=3)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_auth_read_connection_neither_recreates_nor_raw_opens_storage(self):
        from zeekr_control.auth import WebAuth
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'remembered.sqlite3'
            auth=WebAuth({'salt':'00'*16,'digest':'00'*32},remembered_path=path)
            with patch('os.open',side_effect=AssertionError('read connection must use SQLite')):
                with closing(auth._connect()) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM remembered_sessions').fetchone()[0],0)
            path.unlink()
            with self.assertRaises(FileNotFoundError):auth._connect()
            self.assertFalse(path.exists())

    def entries(self, root):
        from zeekr_control.field_reviews import FieldReviewStore
        from zeekr_control.periodic_report import PeriodicDelivery
        from zeekr_control.snapshot_archive import SnapshotArchive
        from zeekr_control.query_policy import QueryPolicy
        from zeekr_control.auth import WebAuth
        def review():
            with closing(FieldReviewStore(root/'reviews.sqlite3').connect()):pass
        def periodic():
            with PeriodicDelivery(root/'periodic.sqlite3').connect():pass
        def archive():
            SnapshotArchive(root/'archive').append('synthetic-session','synthetic-car','{}',None,
                                                  1704067200000,1704067200000)
        def queries():
            with closing(QueryPolicy(root/'queries.sqlite3')._connect()):pass
        def remembered():
            WebAuth({'salt':'00'*16,'digest':'00'*32},remembered_path=root/'remembered.sqlite3')
        return [('review',root/'reviews.sqlite3',review),('periodic',root/'periodic.sqlite3',periodic),
                ('archive',root/'archive/2024/01.sqlite3',archive),('queries',root/'queries.sqlite3',queries),
                ('remembered',root/'remembered.sqlite3',remembered)]

    def test_additional_existing_databases_never_raw_open_their_inode(self):
        with tempfile.TemporaryDirectory() as folder:
            for label,path,entry in self.entries(Path(folder)):
                with self.subTest(store=label):
                    entry();self.assertTrue(path.exists())
                    raw_open=os.open
                    def guarded(candidate,*args,**kwargs):
                        if Path(candidate)==path:raise AssertionError('existing SQLite inode must only be opened by SQLite')
                        return raw_open(candidate,*args,**kwargs)
                    with patch('os.open',side_effect=guarded):entry()
