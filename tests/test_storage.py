"""Offline tests: identifiers and observations are synthetic, never owner records."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from zeekr_control.storage import save, load, clear
from zeekr_control.client import ApiError


class StorageTests(unittest.TestCase):
    @unittest.skipUnless(Path('/dev/fd').is_dir(),'requires descriptor inventory')
    def test_directory_rejection_does_not_leak_file_descriptors(self):
        with tempfile.TemporaryDirectory() as directory:
            before=len(os.listdir('/dev/fd'))
            for _ in range(10):
                with self.assertRaises(ApiError):load(Path(directory))
            self.assertEqual(len(os.listdir('/dev/fd')),before)

    def test_deep_json_is_a_controlled_storage_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'session.json'
            path.write_text('['*10000+'0'+']'*10000)
            path.chmod(0o600)
            with self.assertRaises(ApiError):load(path)

    @unittest.skipUnless(hasattr(os,'mkfifo'),'requires FIFO support')
    def test_named_pipe_is_rejected_without_waiting_for_a_writer(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'session.json'
            os.mkfifo(path,0o600)
            code=('import sys; from zeekr_control.storage import load; from zeekr_control.errors import ApiError\n'
                  'try: load(sys.argv[1])\n'
                  'except ApiError: sys.exit(0)\n'
                  'sys.exit(1)\n')
            result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,timeout=2)
            self.assertEqual(result.returncode,0,result.stderr)

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
