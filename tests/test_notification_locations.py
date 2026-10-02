"""Notification location references use synthetic telemetry and no real network."""
import tempfile
import unittest
from pathlib import Path

try:
    from test_monitor import BASE, sample
except ImportError:
    from tests.test_monitor import BASE, sample
from zeekr_control.monitor import Monitor, message_for
from zeekr_control.notifications import DeliveryError


class NotificationLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.monitor = Monitor(Path(self.temp.name) / 'private' / 'tracks.sqlite3')
        self.monitor.address_resolver = lambda location: (
            '浦东新区·测试园区' if location and location.get('trusted') is True else None)

    def record(self, seconds, vehicle='test-vehicle', trusted=True, observed=None, **position):
        raw = sample(seconds)
        raw['position'].update(posCanBeTrusted=trusted, **position)
        self.monitor.tracks.record(vehicle, raw, BASE + (seconds if observed is None else observed) * 1000, 180)

    def start_charge(self, seconds=600, trusted=False, missing=False):
        raw = sample(seconds, code='charging', dc_lid=1)
        raw['position']['posCanBeTrusted'] = trusted
        if missing:
            raw.pop('position')
        self.monitor.observe('test-vehicle', raw, BASE + seconds * 1000)

    def send(self, seconds=600):
        sent = []
        self.monitor.deliver(sent.append, BASE + seconds * 1000)
        self.assertEqual(len(sent), 1)
        return sent[0], self.monitor.events()[0]['summary']

    def test_recent_trusted_point_is_labeled_and_raw_location_stays_untrusted(self):
        self.record(360)
        self.record(420)
        self.record(540, trusted=False)
        self.start_charge()
        text, data = self.send()
        self.assertIn('浦东新区·测试园区附近（参考位置，3分钟前可信定位）', text)
        self.assertIs(data['start_location']['trusted'], False)
        self.assertEqual(data['start_location_reference']['state_time'], BASE + 420000)
        self.assertEqual(data['start_location_reference']['age_seconds'], 180)

    def test_current_trusted_point_has_priority(self):
        self.record(420)
        self.start_charge(trusted=True)
        text, data = self.send()
        self.assertIn('充电地点：浦东新区·测试园区附近', text)
        self.assertNotIn('参考位置', text)
        self.assertNotIn('start_location_reference', data)

    def test_five_minute_boundary_and_missing_current_location(self):
        self.record(300)
        self.start_charge(missing=True)
        text, data = self.send()
        self.assertIn('5分钟前可信定位', text)
        self.assertIs(data['start_location']['valid'], False)

    def test_stale_future_other_vehicle_and_invalid_points_do_not_fill_location(self):
        self.record(299, observed=599)
        self.record(601)
        self.record(599, vehicle='other-vehicle')
        self.record(599, latitude=0, longitude=0)
        self.record(598, marsCoordinates=None)
        self.start_charge()
        text, data = self.send()
        self.assertIn('充电地点：位置未知', text)
        self.assertNotIn('参考位置', text)
        self.assertNotIn('start_location_reference', data)

    def test_invalid_latest_point_is_skipped_for_earlier_valid_point(self):
        self.record(420)
        self.record(540, latitude=0, longitude=0)
        self.start_charge()
        text, data = self.send()
        self.assertIn('3分钟前可信定位', text)
        self.assertEqual(data['start_location_reference']['state_time'], BASE + 420000)

    def test_subminute_reference_does_not_claim_zero_minutes(self):
        self.record(570)
        self.start_charge()
        text, _ = self.send()
        self.assertIn('30秒前可信定位', text)

    def test_retry_after_restart_preserves_reference_and_exact_message(self):
        self.record(420)
        self.start_charge()
        attempted = []
        def reject(text):
            attempted.append(text)
            raise DeliveryError('synthetic retry')
        self.monitor.deliver(reject, BASE + 600000)
        self.record(590)
        self.monitor = Monitor(self.monitor.tracks.path)
        self.monitor.address_resolver = lambda location: self.fail('Frozen report must not re-resolve')
        text, data = self.send(660)
        self.assertEqual(text, attempted[0])
        self.assertIn('3分钟前可信定位', text)
        self.assertEqual(data['start_location_reference']['state_time'], BASE + 420000)

    def test_legacy_message_also_marks_reference(self):
        self.record(420)
        self.start_charge()
        _, data = self.send()
        data.pop('report_v2')
        text = message_for('charge_start', data, 'synthetic')
        self.assertIn('参考位置，3分钟前可信定位', text)

    def test_saved_report_preview_keeps_reference_warning(self):
        from zeekr_control.report_preview import preview
        self.record(420)
        self.start_charge()
        self.send()
        result = preview(database_path=self.monitor.tracks.path, event_id=self.monitor.events()[0]['id'])
        self.assertIn('参考位置，3分钟前可信定位', result['text'])

    def test_report_budget_never_truncates_reference_warning_into_a_current_place(self):
        from zeekr_control.report_render import render
        self.record(420)
        self.start_charge()
        _, data = self.send()
        for target in (1900, 1100, 300):
            with self.subTest(target=target):
                text, _ = render('charge_start', data['report_v2'], 'synthetic',
                    {'start': '浦东新区·' + '很长园区名称' * 20}, target=target,
                    references={'start': data['start_location_reference']})
                if '充电地点：' in text:
                    self.assertIn('参考位置，3分钟前可信定位', text)
                self.assertLessEqual(len(text.encode()), 2048)

    def test_trip_end_resolves_each_endpoint_relative_to_its_event_time(self):
        self.record(0)
        self.record(180)
        for seconds, changes in ((60, {'speed': 30, 'engine': 'engine_on', 'ready': 1, 'km': 101}),
                                 (240, {'km': 110})):
            raw = sample(seconds, **changes)
            raw['position']['posCanBeTrusted'] = False
            self.monitor.observe('test-vehicle', raw, BASE + seconds * 1000)
        for seconds in range(300, 841, 60):
            raw = sample(seconds, km=110)
            raw['position']['posCanBeTrusted'] = False
            self.monitor.observe('test-vehicle', raw, BASE + seconds * 1000)
        sent = []
        self.monitor.deliver(sent.append, BASE + 840000)
        self.assertEqual(len(sent), 1)
        self.assertIn('出发地：浦东新区·测试园区附近（参考位置，1分钟前可信定位）', sent[0])
        self.assertIn('到达地：浦东新区·测试园区附近（参考位置，1分钟前可信定位）', sent[0])

    def test_geocoder_failure_does_not_block_notification_or_claim_a_reference(self):
        self.record(420)
        self.start_charge()
        self.monitor.address_resolver = lambda location: None
        text, _ = self.send()
        self.assertIn('充电地点：位置未知', text)
        self.assertNotIn('参考位置', text)

    def test_charge_end_references_charge_start_instead_of_stop_location(self):
        self.record(420)
        self.start_charge()
        self.monitor.observe('test-vehicle', sample(660), BASE + 660000)
        sent = []
        self.monitor.deliver(sent.append, BASE + 660000)
        self.assertEqual(len(sent), 2)
        self.assertTrue(all('参考位置，3分钟前可信定位' in text for text in sent))
