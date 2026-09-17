"""Offline tests: identifiers and observations are synthetic, never owner records."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from zeekr_control.storage import save, load, clear
from zeekr_control.client import ApiError


class StorageTests(unittest.TestCase):
    def test_round_trip_private_atomic_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private' / 'session.json'
            save(path, {'accessToken': 'secret'})
            self.assertEqual(load(path)['accessToken'], 'secret')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            save(path, {'accessToken': 'new'})
            self.assertEqual(load(path)['accessToken'], 'new')
            clear(path)
            self.assertEqual(load(path), {})

    def test_insecure_or_invalid_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            path.write_text('{"accessToken":"secret"}')
            path.chmod(0o644)
            with self.assertRaises(ApiError):
                load(path)
            path.chmod(0o600)
            path.write_text('[]')
            with self.assertRaises(ApiError):
                load(path)

    def test_symlink_not_read_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_text('original')
            path = Path(directory) / 'session.json'
            path.symlink_to(target)
            with self.assertRaises(ApiError):
                save(path, {'accessToken': 'new'})
            with self.assertRaises(ApiError):
                load(path)
            self.assertEqual(target.read_text(), 'original')
