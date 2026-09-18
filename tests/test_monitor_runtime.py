import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from zeekr_control.storage import save
from test_monitor import BASE, sample


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('zeekr_control.monitor_runtime'), '后台监控尚未实现')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private'
        save(self.root / 'session.json', {'accessToken': 'synthetic'})

    def runner(self, client):
        from zeekr_control.monitor_runtime import Runner
        return Runner(self.root / 'session.json', client_factory=client, sender=lambda message: None)

    def test_binding_follows_vehicle_identity_not_list_order(self):
        class Client:
            order = ['L6T79X2Z0NP000001']
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': v} for v in self.order]
            def status(self, vin):
                if vin != 'L6T79X2Z0NP000001': raise AssertionError('wrong vehicle')
                return sample(0)
        runner = self.runner(Client)
        runner.tick(BASE)
        Client.order = ['L6T79X2Z0NP000002', 'L6T79X2Z0NP000001']
        runner = self.runner(Client)
        runner.tick(BASE + 1000)
        self.assertEqual(runner.health()['status'], 'unchanged')
        Client.order = ['L6T79X2Z0NP000002']
        runner.tick(BASE + 2000)
        self.assertEqual(runner.health()['status'], 'blocked')

    def test_successful_tick_publishes_shared_snapshot(self):
        class Client:
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin): return sample(0)
        runner = self.runner(Client)
        runner.tick(BASE)
        from zeekr_control.snapshots import SnapshotStore, session_scope
        snapshot = SnapshotStore(self.root / 'snapshots.sqlite3').read(
            session_scope({'accessToken': 'synthetic'}),
            __import__('hashlib').sha256(b'L6T79X2Z0NP000001').hexdigest())
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot['raw']['updateTime'], BASE)

    def test_multiple_vehicles_require_explicit_selection(self):
        class Client:
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}, {'vin': 'L6T79X2Z0NP000002'}]
            def status(self, vin): raise AssertionError('must not query')
        runner = self.runner(Client)
        runner.tick(BASE)
        self.assertEqual(runner.health()['status'], 'blocked')

    def test_credentials_error_waits_for_session_change_without_requery(self):
        from zeekr_control.errors import ApiError
        class Client:
            calls = 0
            def __init__(self, session): pass
            def vehicles(self):
                Client.calls += 1
                raise ApiError('网关 HTTP 401；未自动重试。')
        runner = self.runner(Client)
        runner.tick(BASE)
        runner.tick(BASE + 60000)
        self.assertEqual(Client.calls, 1)
        save(self.root / 'session.json', {'accessToken': 'new-synthetic'})
        runner.tick(BASE + 120000)
        self.assertEqual(Client.calls, 2)

    def test_process_lock_rejects_second_monitor(self):
        from zeekr_control.monitor_runtime import process_lock
        with process_lock(self.root / 'monitor.lock'):
            with self.assertRaisesRegex(ValueError, '运行'):
                with process_lock(self.root / 'monitor.lock'):
                    self.fail('second monitor started')

    def test_cli_accepts_monitor_and_status_commands(self):
        from zeekr_control.cli import parser
        args = parser().parse_args(['monitor', '--once'])
        self.assertTrue(args.once)
        args = parser().parse_args(['monitor-status'])
        self.assertEqual(args.command, 'monitor-status')


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'private' / 'webhook.json'
        save(self.path, {'webhook_url': 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=synthetic-key-for-tests'})

    def test_success_sends_utf8_text_and_rejects_provider_failure(self):
        from zeekr_control.notifications import WeComSender, DeliveryError
        import io
        class Opener:
            code = 0
            def open(self, request, timeout):
                payload = json.loads(request.data)
                if payload != {'msgtype': 'text', 'text': {'content': '测试'}}:
                    raise AssertionError('wrong message payload')
                return io.BytesIO(json.dumps({'errcode': self.code}).encode())
        opener = Opener()
        with patch('zeekr_control.notifications.build_opener', return_value=opener):
            WeComSender(self.path)('测试')
            opener.code = 45009
            with self.assertRaises(DeliveryError) as caught:
                WeComSender(self.path)('测试')
            self.assertFalse(caught.exception.ambiguous)
            self.assertFalse(caught.exception.permanent)

    def test_unsafe_url_is_rejected_before_network(self):
        from zeekr_control.notifications import WeComSender, DeliveryError
        save(self.path, {'webhook_url': 'https://evil.invalid/?key=DO-NOT-EXPOSE'})
        with self.assertRaises(DeliveryError) as caught:
            WeComSender(self.path)('测试')
        self.assertNotIn('DO-NOT-EXPOSE', str(caught.exception))
        self.assertTrue(caught.exception.permanent)

    def test_transport_error_is_ambiguous_and_secret_is_not_logged(self):
        from zeekr_control.notifications import WeComSender, DeliveryError
        with patch('zeekr_control.notifications.build_opener') as factory:
            factory.return_value.open.side_effect = URLError('SECRET-IN-URL')
            with self.assertRaises(DeliveryError) as caught:
                WeComSender(self.path)('测试')
        self.assertTrue(caught.exception.ambiguous)
        self.assertNotIn('SECRET', str(caught.exception))
