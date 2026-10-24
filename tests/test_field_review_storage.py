"""Manual review storage boundaries use only temporary private files."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.field_reviews import FieldReviewStore

PATH='synthetic.parameter'


class FieldReviewStorageTests(unittest.TestCase):
    def test_schema_initialization_failure_rolls_back_and_closes_connection(self):
        db=sqlite3.connect(self.store.path)
        try:
            db.execute('CREATE TABLE sentinel(value TEXT)')
            db.execute('CREATE INDEX reviews ON sentinel(value)')
            db.commit()
        finally:db.close()
        self.store.path.chmod(0o600);before=self.store.path.read_bytes()
        connections=[];connect=sqlite3.connect
        class TrackedConnection(sqlite3.Connection):
            closed=False
            def close(self):
                self.closed=True
                super().close()
        def tracked(*args,**kwargs):
            connection=connect(*args,**kwargs,factory=TrackedConnection)
            connections.append(connection);self.addCleanup(connection.close)
            return connection
        with patch('zeekr_control.field_reviews.sqlite3.connect',side_effect=tracked):
            with self.assertRaises(sqlite3.OperationalError):self.store.connect()
        with self.subTest(boundary='connection closed'):
            self.assertTrue(connections[0].closed)
        with self.subTest(boundary='original schema and bytes preserved'):
            self.assertEqual(self.store.path.read_bytes(),before)

    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name);self.store=FieldReviewStore(self.root/'reviews.sqlite3')

    def update(self,revision=0):
        return self.store.update('car',dict(vehicle='car',revision=revision,action='save',path=PATH,
                                 scope='value',raw='0',status='confirmed',meaning='synthetic closed'),{PATH})

    def test_missing_read_creates_no_directory_or_database(self):
        store=FieldReviewStore(self.root/'missing/reviews.sqlite3')
        self.assertEqual(store.read('car')['revision'],0)
        self.assertFalse(store.path.parent.exists())

    def test_read_does_not_initialize_schema_in_an_unrecognized_database(self):
        with sqlite3.connect(self.store.path) as db:db.execute('CREATE TABLE sentinel(value TEXT)')
        self.store.path.chmod(0o600);before=self.store.path.read_bytes()
        try:self.store.read('car')
        except sqlite3.Error:pass
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_readable_readonly_database_can_still_be_read(self):
        expected=self.update();self.store.path.chmod(0o400)
        self.assertEqual(self.store.read('car'),expected)
        self.assertEqual(self.store.path.stat().st_mode&0o777,0o400)

    def test_hardlinked_database_is_rejected_without_initializing_other_file(self):
        other=self.root/'other.sqlite3'
        with sqlite3.connect(other) as db:db.execute('CREATE TABLE sentinel(value TEXT)')
        other.chmod(0o600);os.link(other,self.store.path);before=other.read_bytes()
        error=None
        try:self.store.read('car')
        except OSError as caught:error=caught
        self.assertEqual(other.read_bytes(),before)
        self.assertIsInstance(error,OSError)
        with self.assertRaises(OSError):self.update()
        self.assertEqual(other.read_bytes(),before)
        self.store.path.unlink()
        self.update()
        self.assertEqual(self.store.read('car')['revision'],1)
        self.assertEqual(other.read_bytes(),before)

    def test_permissive_file_or_parent_is_refused_without_permission_changes(self):
        self.update()
        for path in (self.store.path,self.root):
            mode=0o644 if path==self.store.path else 0o755
            original=path.stat().st_mode&0o777;path.chmod(mode)
            try:
                for action in (lambda:self.store.read('car'),lambda:self.update(1)):
                    with self.subTest(path=path.name,action=action),self.assertRaises(OSError):action()
                self.assertEqual(path.stat().st_mode&0o777,mode)
            finally:path.chmod(original)

    def test_symlink_parent_and_broken_file_are_refused_before_sqlite(self):
        private=self.root/'private';private.mkdir(mode=0o700)
        FieldReviewStore(private/'reviews.sqlite3').connect().close()
        alias=self.root/'alias';alias.symlink_to(private,target_is_directory=True)
        broken=private/'broken.sqlite3';broken.symlink_to(private/'absent')
        with patch('zeekr_control.field_reviews.sqlite3.connect',side_effect=AssertionError('SQLite must not open')):
            for store in (FieldReviewStore(alias/'reviews.sqlite3'),FieldReviewStore(broken)):
                with self.subTest(path=str(store.path)),self.assertRaises(OSError):store.read('car')
