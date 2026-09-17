import base64
import contextlib
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.cli import main, parser
from zeekr_control.storage import load, save


class HistoryConnectTests(unittest.TestCase):
    def setUp(self):
        self.assertIn('history-connect', parser().format_help(), 'History credential import is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'private' / 'session.json'
        self.original = {'accessToken': 'KEEP-GW2', 'userId': 'user'}
        save(self.path, self.original)

    def run_connect(self, inputs, tty=True):
        output = io.StringIO()
        with patch('sys.stdin.isatty', return_value=tty), \
             patch('zeekr_control.cli.Client.vehicles', return_value=[{'vin': 'L6T79X2Z0NP000001'}]), \
             patch('getpass.getpass', side_effect=inputs), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = main(['history-connect'], self.path)
        return result, output.getvalue()

    def test_import_preserves_existing_session_and_never_prints_credentials(self):
        vin = base64.b64encode(b'x' * 32).decode()
        result, output = self.run_connect(['HISTORY-SECRET', 'private-device', vin])
        self.assertEqual(result, 0)
        stored = load(self.path)
        self.assertEqual(stored['accessToken'], 'KEEP-GW2')
        self.assertEqual(stored['historyAccessToken'], 'HISTORY-SECRET')
        self.assertEqual(stored['historyVehicleKey'], hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest())
        for secret in ('HISTORY-SECRET', 'private-device', vin):
            self.assertNotIn(secret, output)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_invalid_import_and_noninteractive_use_leave_session_unchanged(self):
        result, _ = self.run_connect(['secret', 'device', 'bad-vin'])
        self.assertEqual(result, 1)
        self.assertEqual(load(self.path), self.original)
        result, _ = self.run_connect([], tty=False)
        self.assertEqual(result, 1)
        self.assertEqual(load(self.path), self.original)
