import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BarkSenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / 'bark.json'

    def tearDown(self):
        self.temp.cleanup()

    def test_posts_v2_payload_without_exposing_device_key(self):
        from zeekr_control.notifications import BarkSender
        self.config.write_text(json.dumps({
            'base_url': 'https://rocstarrobotics.com/bark',
            'device_key': 'SECRET_DEVICE_KEY'}))
        self.config.chmod(0o600)
        captured = {}

        class Opener:
            def open(self, request, timeout):
                captured['url'] = request.full_url
                captured['payload'] = json.loads(request.data)
                return io.BytesIO(b'{"code":200,"message":"success"}')

        with patch('zeekr_control.notifications.build_opener', return_value=Opener()):
            BarkSender(self.config)('极氪开始充电', '时间：09月21日 18:26')

        self.assertEqual(captured['url'], 'https://rocstarrobotics.com/bark/push')
        self.assertEqual(captured['payload'], {
            'device_key': 'SECRET_DEVICE_KEY', 'title': '极氪开始充电',
            'body': '时间：09月21日 18:26', 'group': 'Zeekr',
            'level': 'active'})

    def test_rejected_response_is_permanent_and_hides_secret(self):
        from zeekr_control.notifications import BarkSender, DeliveryError
        self.config.write_text(json.dumps({
            'base_url': 'https://rocstarrobotics.com/bark/',
            'device_key': 'SECRET_DEVICE_KEY'}))
        self.config.chmod(0o600)

        class Opener:
            def open(self, request, timeout):
                return io.BytesIO(b'{"code":400,"message":"bad SECRET_DEVICE_KEY"}')

        with patch('zeekr_control.notifications.build_opener', return_value=Opener()):
            with self.assertRaises(DeliveryError) as caught:
                BarkSender(self.config)('标题', '正文')
        self.assertTrue(caught.exception.permanent)
        self.assertNotIn('SECRET_DEVICE_KEY', str(caught.exception))

    def test_fallback_uses_wecom_only_after_bark_failure(self):
        from zeekr_control.notifications import DeliveryError, FallbackSender
        calls = []

        def bark(message):
            calls.append(('bark', message))
            raise DeliveryError('Bark 被拒绝', permanent=True)

        sender = FallbackSender(bark, lambda message: calls.append(('wecom', message)))
        sender('提醒正文')
        self.assertEqual(calls, [('bark', '提醒正文'), ('wecom', '提醒正文')])

    def test_fallback_does_not_duplicate_ambiguous_bark_delivery(self):
        from zeekr_control.notifications import DeliveryError, FallbackSender
        calls = []
        def bark(message):
            raise DeliveryError('结果未知', ambiguous=True)
        sender = FallbackSender(bark, calls.append)
        with self.assertRaises(DeliveryError):
            sender('提醒正文')
        self.assertEqual(calls, [])

    def test_fallback_formats_bark_time_but_preserves_wecom_seconds(self):
        from zeekr_control.notifications import DeliveryError, FallbackSender, compact_bark_times
        calls = []
        def bark(message):
            calls.append(('bark', message))
            raise DeliveryError('Bark 被拒绝', permanent=True)
        sender = FallbackSender(bark, lambda message: calls.append(('wecom', message)),
                                primary_transform=compact_bark_times)
        original = '车辆观测：2026-09-22 14:30:45（北京时间）\n缓存可能延迟。'
        sender(original)
        self.assertEqual(calls, [
            ('bark', '车辆观测：2026年09月22日 14:30\n缓存可能延迟。'),
            ('wecom', original)])


class BarkEventRoutingTests(unittest.TestCase):
    def setUp(self):
        from zeekr_control.monitor import Monitor
        self.temp = tempfile.TemporaryDirectory()
        self.monitor = Monitor(Path(self.temp.name) / 'tracks.sqlite3')
        self.base = 1789970000000

    def tearDown(self):
        self.temp.cleanup()

    def _event(self, kind, partial=False):
        data = dict(start_time=self.base, end_time=self.base + 60000,
                    duration_seconds=60, distance_km=1.2, start_soc=50,
                    end_soc=49, soc_delta=-1, partial=partial,
                    start_location=None, end_location=None,
                    start_address=None, end_address=None,
                    addresses_resolved=True)
        with self.monitor.tracks.connect() as db:
            self.monitor._event(db, 'car', kind, data, self.base + 120000)

    def test_charge_start_uses_bark_without_wecom_detail(self):
        self._event('charge_start')
        bark, wecom = [], []
        self.monitor.deliver(wecom.append, self.base + 180000,
                             alert_sender=lambda title, body: bark.append((title, body)))
        self.assertEqual(len(bark), 1)
        self.assertEqual(bark[0][0], '⚡ 极氪开始充电')
        self.assertIn('电量：50%', bark[0][1])
        self.assertEqual(wecom, [])
        event = self.monitor.events()[0]
        self.assertEqual((event['alert_delivery'], event['delivery']), ('sent', 'sent'))

    def test_trip_start_uses_bark_once_without_wecom_detail(self):
        self._event('trip_start')
        bark, wecom = [], []
        self.monitor.deliver(wecom.append, self.base + 180000,
                             alert_sender=lambda title, body: bark.append((title, body)))
        self.monitor.deliver(wecom.append, self.base + 240000,
                             alert_sender=lambda title, body: bark.append((title, body)))
        self.assertEqual(len(bark), 1)
        self.assertEqual(bark[0][0], '🚗 极氪行程开始')
        self.assertEqual(wecom, [])
        event = [e for e in self.monitor.events(include_alerts=True) if e['kind'] == 'trip_start'][0]
        self.assertEqual((event['alert_delivery'], event['delivery']), ('sent', 'sent'))

    def test_bark_event_time_uses_chinese_date_without_seconds(self):
        from zeekr_control.monitor import bark_message_for
        title, body = bark_message_for('charge_start', {
            'start_time': 0, 'start_soc': 50, 'partial': False})
        self.assertEqual(title, '⚡ 极氪开始充电')
        self.assertEqual(body, '时间：1970年01月01日 08:00\n当前电量：50%')

    def test_trip_alert_and_wecom_detail_retry_independently(self):
        from zeekr_control.notifications import DeliveryError
        self._event('trip_end')
        bark, wecom = [], []

        def failed_wecom(message):
            wecom.append(message)
            raise DeliveryError('temporary')

        self.monitor.deliver(failed_wecom, self.base + 180000,
                             alert_sender=lambda title, body: bark.append((title, body)))
        self.monitor.deliver(wecom.append, self.base + 400000,
                             alert_sender=lambda title, body: bark.append((title, body)))
        self.assertEqual(len(bark), 1)
        self.assertEqual(len(wecom), 2)
        event = self.monitor.events()[0]
        self.assertEqual((event['alert_delivery'], event['delivery']), ('sent', 'sent'))


class StorageNotificationRoutingTests(unittest.TestCase):
    def test_storage_change_sends_short_bark_and_detailed_wecom(self):
        from zeekr_control.storage_health import StorageHealth
        with tempfile.TemporaryDirectory() as folder:
            bark, wecom = [], []
            health = StorageHealth(Path(folder), wecom.append,
                                   alert_sender=lambda title, body: bark.append((title, body)))
            health.measure = lambda: {
                'disk_total_bytes': 100, 'disk_used_bytes': 91,
                'disk_free_bytes': 9, 'disk_used_percent': 91.0,
                'inode_used_percent': 20.0, 'data_bytes': 1,
                'archive_bytes': 0, 'trash_bytes': 0, 'scan_complete': True}
            health.tick(1000)
            self.assertEqual(bark[0][0], '⚠️ Zeekr 服务器存储异常')
            self.assertIn('磁盘使用率：91.0%', bark[0][1])
            self.assertIn('极氪服务器存储：严重', wecom[0])
            state = health.cached()
            self.assertEqual((state['alert_notification_state'],
                              state['notification_state']), ('sent', 'sent'))


class RunnerNotificationWiringTests(unittest.TestCase):
    def test_default_runner_routes_detail_alert_and_reminder_channels(self):
        from zeekr_control.monitor_runtime import Runner
        from zeekr_control.notifications import BarkSender, FallbackSender, WeComSender
        with tempfile.TemporaryDirectory() as folder:
            Path(folder).chmod(0o700)
            runner = Runner(Path(folder) / 'session.json')
            try:
                self.assertIsInstance(runner.sender, WeComSender)
                self.assertIsInstance(runner.alert_sender, BarkSender)
                self.assertIsInstance(runner.reminder_sender, FallbackSender)
                self.assertIs(runner.storage_health.alert_sender, runner.alert_sender)
            finally:
                runner.insight_worker.close()

    def test_public_status_reads_pre_bark_database_during_service_startup(self):
        import sqlite3
        from zeekr_control.monitor_runtime import read_status
        from zeekr_control.storage import save
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with sqlite3.connect(root / 'tracks.sqlite3') as db:
                db.execute('''CREATE TABLE monitor_events (
                    id TEXT PRIMARY KEY, vehicle TEXT, kind TEXT, summary TEXT,
                    message TEXT, created INTEGER, delivery TEXT, attempts INTEGER,
                    next_attempt INTEGER, error TEXT, sent_at INTEGER)''')
                db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           ('old','car','trip_end','{}','old',1,'sent',1,0,None,1))
            save(root / 'monitor-health.json', {'status':'fresh','heartbeat':'1','next_check':'1'})
            result = read_status(root, 'car', public=True)
            self.assertEqual(result['events'][0]['alert_delivery'], None)

if __name__ == '__main__':
    unittest.main()
