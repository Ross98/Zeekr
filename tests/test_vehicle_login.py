"""Offline vehicle reauthentication; no real SMS or credentials."""
import tempfile
import threading
import unittest
from pathlib import Path

from zeekr_control.storage import load, save
from zeekr_control.errors import ApiError
from zeekr_control.vehicle_login import VehicleLogin


class FakeClient:
    fail = False
    account = 'owner'
    calls = 0

    def __init__(self, session):
        self.session = {'deviceId': 'test-device'}

    def send_sms(self, phone):
        type(self).calls += 1

    def login_sms(self, phone, code):
        if self.fail:
            raise ApiError('private upstream payload 13800000000 123456')
        self.session.update(accessToken='new-token', userId=self.account, clientId='client')

    def vehicles(self):
        return [{'vin': 'L6T79X2Z0NP000001'}]


class VehicleLoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'session.json'
        self.old = {'accessToken': 'old-token', 'userId': 'owner'}
        save(self.path, self.old)
        FakeClient.fail, FakeClient.account, FakeClient.calls = False, 'owner', 0
        self.now = 1000
        self.login = VehicleLogin(self.path, FakeClient, threading.RLock(), lambda: self.now)
        self.addCleanup(self.tmp.cleanup)

    def begin(self):
        status, value = self.login.send({'phone': '13800000000'}, 'browser')
        self.assertEqual(status, 200)
        self.assertNotIn('13800000000', str(value))
        return value['challenge']

    def finish(self, challenge, owner='browser'):
        return self.login.verify({'challenge': challenge, 'code': '123456'}, owner)

    def test_success_saves_only_after_vehicle_validation_and_consumes_challenge(self):
        challenge = self.begin()
        self.assertEqual(load(self.path), self.old)
        self.assertEqual(self.finish(challenge)[0], 200)
        self.assertEqual(load(self.path)['accessToken'], 'new-token')
        self.assertEqual(self.finish(challenge)[0], 400)

    def test_error_is_redacted_and_preserves_old_session(self):
        challenge = self.begin()
        FakeClient.fail = True
        status, value = self.finish(challenge)
        self.assertEqual(status, 502)
        self.assertNotIn('13800000000', str(value))
        self.assertNotIn('123456', str(value))
        self.assertEqual(load(self.path), self.old)

    def test_other_browser_expired_and_account_change_rejected(self):
        challenge = self.begin()
        self.assertEqual(self.finish(challenge, 'other')[0], 400)
        FakeClient.account = 'other-account'
        self.assertEqual(self.finish(challenge)[0], 409)
        self.assertEqual(load(self.path), self.old)
        self.now += 601
        self.assertEqual(self.finish(challenge)[0], 400)

    def test_session_changed_during_sms_flow_not_overwritten(self):
        challenge = self.begin()
        save(self.path, {'accessToken': 'cli-new', 'userId': 'owner'})
        self.assertEqual(self.finish(challenge)[0], 409)
        self.assertEqual(load(self.path)['accessToken'], 'cli-new')

    def test_server_enforces_sms_and_verification_limits(self):
        challenge = self.begin()
        self.assertEqual(self.login.send({'phone': '13800000000'}, 'browser')[0], 429)
        FakeClient.fail = True
        for _ in range(5):
            self.assertEqual(self.finish(challenge)[0], 502)
        self.assertEqual(self.finish(challenge)[0], 429)
        self.assertEqual(FakeClient.calls, 1)

    def test_no_vehicle_or_wrong_binding_preserves_session(self):
        from unittest.mock import patch
        challenge = self.begin()
        with patch.object(FakeClient, 'vehicles', return_value=[]):
            self.assertEqual(self.finish(challenge)[0], 409)
        save(self.path.parent / 'monitor-binding.json', {'vehicle_key': 'wrong'})
        self.assertEqual(self.finish(challenge)[0], 409)
        self.assertEqual(load(self.path), self.old)

    def test_malformed_input_does_not_send_sms(self):
        for phone in (None, [], 'wrong', '13800000000\n'):
            self.assertEqual(self.login.send({'phone': phone}, 'browser')[0], 400)
        self.assertEqual(FakeClient.calls, 0)

    def test_send_window_limit_expiry_and_new_challenge(self):
        first = self.begin()
        for _ in range(4):
            self.now += 60
            latest = self.begin()
        self.assertEqual(self.finish(first)[0], 400)
        self.now += 60
        self.assertEqual(self.login.send({'phone': '13800000000'}, 'browser')[0], 429)
        self.now += 901
        self.assertEqual(self.finish(latest)[0], 400)
        self.begin()

    def test_inflight_request_rejected_without_extra_sms(self):
        self.login.lock.acquire()
        try:
            self.assertEqual(self.login.send({'phone': '13800000000'}, 'browser')[0], 409)
            self.assertEqual(self.finish('test')[0], 409)
        finally:
            self.login.lock.release()
        self.assertEqual(FakeClient.calls, 0)

    def test_storage_failure_preserves_session_and_does_not_expose_tokens(self):
        from unittest.mock import patch
        challenge = self.begin()
        with patch('zeekr_control.vehicle_login.save', side_effect=OSError('new-token')):
            status, result = self.finish(challenge)
        self.assertEqual(status, 500)
        self.assertNotIn('new-token', str(result))
        self.assertEqual(load(self.path), self.old)

    def test_history_files_unchanged_by_reconnect(self):
        history = self.path.parent / 'personal.sqlite3'
        history.write_bytes(b'synthetic history sentinel')
        self.assertEqual(self.finish(self.begin())[0], 200)
        self.assertEqual(history.read_bytes(), b'synthetic history sentinel')

    def test_verification_global_limit_cannot_be_reset_with_new_sms(self):
        FakeClient.fail = True
        for _ in range(3):
            challenge = self.begin()
            for _ in range(5):
                self.assertEqual(self.finish(challenge)[0], 502)
            self.now += 60
        self.assertEqual(self.finish(self.begin())[0], 429)

    def test_first_connection_and_send_failure(self):
        from unittest.mock import patch
        self.path.unlink()
        with patch.object(FakeClient, 'send_sms', side_effect=TimeoutError('private phone')):
            status, result = self.login.send({'phone': '13800000000'}, 'browser')
        self.assertEqual(status, 502)
        self.assertNotIn('private phone', str(result))
        self.assertFalse(self.path.exists())
        self.now += 60
        self.assertEqual(self.finish(self.begin())[0], 200)

    def test_upstream_timeout_and_session_change_during_vehicle_lookup(self):
        from unittest.mock import patch
        challenge = self.begin()
        with patch.object(FakeClient, 'vehicles', side_effect=TimeoutError()):
            self.assertEqual(self.finish(challenge)[0], 502)
        self.assertEqual(load(self.path), self.old)
        def concurrent_update():
            save(self.path, {'accessToken': 'concurrent', 'userId': 'owner'})
            return [{'vin': 'L6T79X2Z0NP000001'}]
        with patch.object(FakeClient, 'vehicles', side_effect=concurrent_update):
            self.assertEqual(self.finish(challenge)[0], 409)
        self.assertEqual(load(self.path)['accessToken'], 'concurrent')

    def test_untrusted_unicode_challenge_is_a_validation_error(self):
        self.begin()
        status, _ = self.login.verify({'challenge': chr(0x4e2d), 'code': '123456'}, 'browser')
        self.assertEqual(status, 400)
