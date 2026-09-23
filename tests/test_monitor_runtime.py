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

    def test_runner_uses_same_private_amap_config_for_static_trip_maps(self):
        from zeekr_control.monitor_runtime import Runner
        from zeekr_control.trip_map import AmapStaticMap
        runner = Runner(self.root / 'session.json', client_factory=lambda session: None,
                        sender=lambda message: None)
        self.addCleanup(lambda: runner.insight_worker.close())
        self.assertIsInstance(runner.monitor.map_renderer, AmapStaticMap)
        self.assertEqual(runner.monitor.map_renderer.config_path, self.root / 'amap-geocoding.json')

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
        import sqlite3
        archive = list((self.root / 'snapshot-archive').glob('*/*.sqlite3'))
        self.assertEqual(len(archive), 1)
        runner.tick(BASE + 60000)  # Same cached vehicle response, distinct read.
        with sqlite3.connect(archive[0]) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reads').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM payloads').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT DISTINCT source FROM reads').fetchall(), [('monitor',)])

    def test_custom_rules_use_collected_data_without_extra_queries_or_real_sender(self):
        import hashlib
        from zeekr_control.personal_store import account_scope
        class Client:
            tick=0;calls=0
            def __init__(self,session):pass
            def vehicles(self):return [{'vin':'L6T79X2Z0NP000001'}]
            def status(self,vin):
                Client.calls+=1
                return sample(Client.tick,soc=20)
        runner=self.runner(Client);messages=[];runner.sender=messages.append
        owner=account_scope({'accessToken':'synthetic'})
        car=hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest()
        runner.reminders.update(owner,car,dict(action='save',revision=0,name='合成提醒',kind='low_soc',threshold=25,
                confirm_seconds=60,cooldown_minutes=60,enabled=True,delivery='wecom',recovery=True))
        runner.tick(BASE);Client.tick=60;runner.tick(BASE+60000)
        self.assertEqual(Client.calls,2)
        self.assertEqual(len(messages),1)
        self.assertEqual(runner.reminders.query(owner,car)['history'][0]['delivery'],'sent')
        restarted=self.runner(Client);restarted.sender=messages.append
        Client.tick=120;restarted.tick(BASE+120000)
        self.assertEqual(len(messages),1)

    def test_multiple_vehicles_require_explicit_selection(self):
        class Client:
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}, {'vin': 'L6T79X2Z0NP000002'}]
            def status(self, vin): raise AssertionError('must not query')
        runner = self.runner(Client)
        runner.tick(BASE)
        self.assertEqual(runner.health()['status'], 'blocked')

    def test_successful_collection_schedules_analysis_without_extra_vehicle_query(self):
        from zeekr_control.monitor_runtime import collection_loop
        from zeekr_control.snapshots import session_scope
        import hashlib
        import threading
        class Client:
            calls = 0
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin):
                Client.calls += 1
                return sample(0)
        runner = self.runner(Client)
        self.addCleanup(lambda: runner.insight_worker.close())
        with patch('zeekr_control.monitor_runtime.time.time', return_value=BASE/1000):
            collection_loop(runner, threading.Event(), once=True)
        self.assertEqual(Client.calls, 1)
        self.assertIsNotNone(runner.insight_worker.thread)
        runner.insight_worker.thread.join(2)
        data = runner.insight_worker.cache.query(session_scope({'accessToken': 'synthetic'}),
            hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest(), BASE, 0)
        self.assertEqual(data['status'], 'ready')
        self.assertEqual(data['report']['quality']['reads'], 1)
        save(self.root/'sampling.json', {'enabled': 'false'})
        runner.tick(BASE+3600000)
        self.assertFalse(runner.start_analysis())

    def test_analysis_context_guard_rejects_changed_session_and_pause(self):
        class Client:
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin): return sample(0)
        runner = self.runner(Client)
        runner.tick(BASE)
        with patch.object(runner.insight_worker, 'start', return_value=True) as start:
            self.assertTrue(runner.start_analysis())
            guard = start.call_args.args[3]
            self.assertTrue(guard())
            save(self.root/'sampling.json', {'enabled': 'false'})
            self.assertFalse(guard())
            save(self.root/'sampling.json', {'enabled': 'true'})
            save(self.root/'session.json', {'accessToken': 'different'})
            self.assertFalse(guard())

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

    def test_gateway_1509_alerts_bark_once_until_success_even_after_restart(self):
        from zeekr_control.errors import ApiError
        from zeekr_control.monitor_runtime import Runner
        messages = []
        class Client:
            valid = False
            def __init__(self, session): pass
            def vehicles(self):
                if not Client.valid:
                    raise ApiError('status 失败，网关代码 1509；会话过期或被替换时请重新登录。')
                return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin): return sample(0)
        def runner():
            value = Runner(self.root/'session.json', client_factory=Client,
                           sender=lambda message: None,
                           alert_sender=lambda title, body: messages.append((title, body)))
            self.addCleanup(value.insight_worker.close)
            return value
        first = runner()
        first.tick(BASE)
        first.tick(BASE + 60000)
        self.assertEqual(len(messages), 1)
        self.assertIn('1509', messages[0][1])
        self.assertIn('重新登录', messages[0][1])
        runner().tick(BASE + 120000)
        self.assertEqual(len(messages), 1)
        Client.valid = True
        save(self.root/'session.json', {'accessToken': 'new-synthetic'})
        runner().tick(BASE + 180000)
        self.assertEqual(len(messages), 1)
        Client.valid = False
        save(self.root/'session.json', {'accessToken': 'another-synthetic'})
        runner().tick(BASE + 240000)
        self.assertEqual(len(messages), 2)

    def test_auth_alert_does_not_send_on_other_blocked_errors(self):
        from zeekr_control.errors import ApiError
        from zeekr_control.monitor_runtime import Runner
        messages = []
        class Client:
            def __init__(self, session): pass
            def vehicles(self): raise ApiError('原绑定车辆不在当前车辆列表中')
        runner = Runner(self.root/'session.json', client_factory=Client,
                        sender=lambda message: None,
                        alert_sender=lambda title, body: messages.append((title, body)))
        self.addCleanup(runner.insight_worker.close)
        runner.tick(BASE)
        self.assertEqual(messages, [])

    def test_auth_alert_uncertain_delivery_is_not_repeated(self):
        from zeekr_control.monitor_runtime import AuthFailureAlert
        from zeekr_control.notifications import DeliveryError
        calls = []
        def uncertain(title, body):
            calls.append((title, body))
            raise DeliveryError('timeout', ambiguous=True)
        alert = AuthFailureAlert(self.root, uncertain)
        alert.blocked('status 失败，网关代码 1509')
        AuthFailureAlert(self.root, uncertain).blocked('status 失败，网关代码 1509')
        self.assertEqual(len(calls), 1)
        self.assertEqual(__import__('zeekr_control.storage', fromlist=['load']).load(
            self.root/'auth-failure-alert.json')['state'], 'uncertain')

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

    def test_public_status_filters_vehicle_and_never_returns_private_summary(self):
        import sqlite3
        from zeekr_control.monitor import Monitor
        from zeekr_control.monitor_runtime import read_status
        Monitor(self.root / 'tracks.sqlite3')
        with sqlite3.connect(self.root / 'tracks.sqlite3') as db:
            for vehicle in ('car-a','car-b'):
                db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                    (vehicle,vehicle,'trip_end',json.dumps({'report_v2':{'secret':'PRIVATE'},'start_location':[1,2]}),'PRIVATE',1))
                db.execute('INSERT INTO monitor_event_alerts(event_id) VALUES(?)', (vehicle,))
        save(self.root/'monitor-health.json', {'status':'fresh','heartbeat':str(BASE),'next_check':str(BASE+60000),
             'signals':'PRIVATE-SIGNALS','raw_future':'PRIVATE-FUTURE'})
        result = read_status(self.root,'car-a',public=True)
        encoded = json.dumps(result)
        self.assertEqual(len(result['events']),1)
        self.assertNotIn('summary',result['events'][0])
        self.assertNotIn('PRIVATE',encoded)
        self.assertNotIn('signals',result)
        self.assertEqual(result['events'][0]['alert_delivery'], 'pending')
        self.assertEqual(read_status(self.root,None,public=True)['events'],[])


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

    def test_utf8_hard_limit_allows_2048_and_rejects_2049(self):
        import io
        class Opener:
            def open(self, request, timeout): return io.BytesIO(b'{"errcode":0}')
        from zeekr_control.notifications import WeComSender, DeliveryError
        with patch('zeekr_control.notifications.build_opener', return_value=Opener()):
            WeComSender(self.path)('a'*2047)
            WeComSender(self.path)('a'*2048)
            with self.assertRaises(DeliveryError): WeComSender(self.path)('a'*2049)
