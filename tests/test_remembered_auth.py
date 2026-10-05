import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zeekr_control.auth import WebAuth, password_record


class RememberedAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = password_record('synthetic remembered password')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'remembered.sqlite3'
        self.auth = WebAuth(self.record, remembered_path=self.path)

    def login(self, days=7, **kwargs):
        return self.auth.login('synthetic remembered password', remember_days=days,
                               client_ip='192.0.2.10', user_agent='Synthetic Browser', **kwargs)

    def valid(self, auth, token, ip='192.0.2.10', agent='Synthetic Browser'):
        return auth.valid(token, client_ip=ip, user_agent=agent)

    def test_fixed_duration_restart_binding_and_no_raw_credentials(self):
        for days in (7, 30):
            with self.subTest(days=days), patch('zeekr_control.auth.time.time', return_value=1000):
                token = self.login(days)
                restarted = WebAuth(self.record, remembered_path=self.path)
                self.assertTrue(self.valid(restarted, token))
                self.assertFalse(self.valid(restarted, token, ip='192.0.2.11'))
                self.assertFalse(self.valid(restarted, token, agent='Another Browser'))
                self.assertFalse(restarted.valid(token))
                self.assertFalse(self.valid(restarted, 'forged'))
            with patch('zeekr_control.auth.time.time', return_value=1000 + days * 86400 - 1):
                self.assertTrue(self.valid(restarted, token))
            with patch('zeekr_control.auth.time.time', return_value=1000 + days * 86400):
                self.assertFalse(self.valid(restarted, token), 'access must not extend expiry')
            content = self.path.read_bytes()
            for secret in (token, 'synthetic remembered password', '192.0.2.10', 'Synthetic Browser'):
                self.assertNotIn(secret.encode(), content)
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_logout_durable_across_instances_and_other_device_unaffected(self):
        token = self.login()
        other = self.login(30)
        restarted = WebAuth(self.record, remembered_path=self.path)
        restarted.logout(token)
        self.assertFalse(self.valid(self.auth, token))
        self.assertFalse(self.valid(WebAuth(self.record, remembered_path=self.path), token))
        self.assertTrue(self.valid(self.auth, other))

    def test_password_change_invalidates_remembered_tokens(self):
        token = self.login()
        changed = WebAuth(password_record('different synthetic password'), remembered_path=self.path)
        self.assertFalse(self.valid(changed, token))

    def test_default_session_stays_twelve_hours_and_does_not_persist(self):
        with patch('zeekr_control.auth.time.time', return_value=1000):
            token = self.auth.login('synthetic remembered password')
            self.assertTrue(self.auth.valid(token))
            self.assertFalse(WebAuth(self.record, remembered_path=self.path).valid(token))
        with patch('zeekr_control.auth.time.time', return_value=1000 + 43200):
            self.assertFalse(self.auth.valid(token))

    def test_input_allowlist_missing_context_and_wrong_password(self):
        for value in (True, False, 7.0, '7', -1, 1, 365, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.auth.login('synthetic remembered password', remember_days=value)
        with self.assertRaises(ValueError):
            self.auth.login('synthetic remembered password', remember_days=7)
        self.assertIsNone(self.auth.login('wrong', remember_days=7,
                                         client_ip='192.0.2.10', user_agent='Synthetic Browser'))
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM remembered_sessions').fetchone()[0], 0)

    def test_remembered_count_bounded_and_sessions_not_confused(self):
        # Avoid running password derivation 33 times: only issuance bounds are under test here.
        with patch('zeekr_control.auth.hashlib.pbkdf2_hmac', return_value=bytes.fromhex(self.record['digest'])):
            with patch('zeekr_control.auth.time.time', return_value=1000):
                oldest = self.login()
            with patch('zeekr_control.auth.time.time', return_value=2000):
                tokens = [self.login(30) for _ in range(32)]
        with patch('zeekr_control.auth.time.time', return_value=2000):
            self.assertFalse(self.valid(self.auth, oldest))
            self.assertTrue(all(self.valid(self.auth, token) for token in tokens))
        with patch('zeekr_control.auth.time.time', return_value=3000):
            newest = self.login(7)
            self.assertTrue(self.valid(self.auth, newest), 'new 7-day login must survive 32 old 30-day sessions')
            self.assertEqual(sum(self.valid(self.auth, token) for token in tokens), 31)

    def test_storage_failure_fails_closed(self):
        token = self.login()
        self.path.unlink()
        self.path.mkdir()
        self.assertFalse(self.valid(self.auth, token))
        with self.assertRaises((OSError, sqlite3.Error)):
            self.login()

    def test_rejects_symlink_and_unsafe_storage(self):
        link = Path(self.directory.name) / 'linked.sqlite3'
        link.symlink_to(self.path)
        with self.assertRaises((ValueError, OSError)):
            WebAuth(self.record, remembered_path=link)
        os.chmod(self.path, 0o644)
        with self.assertRaises((ValueError, OSError)):
            WebAuth(self.record, remembered_path=self.path)
