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

    def test_saved_label_has_priority_over_geocoder_and_is_frozen(self):
        from unittest.mock import Mock
        self.start_charge(trusted=True)
        self.monitor.place_resolver=lambda vehicle,kind,data,identity: {
            'start':dict(name='我标注的车库',reference=dict(source='saved_place',side='start',position_source='direct'))}
        self.monitor.address_resolver=Mock(side_effect=AssertionError('Saved label must skip external geocoder'))
        text,data=self.send()
        self.assertIn('充电地点：我标注的车库附近（已标注地点）',text)
        self.assertEqual(data['start_location_reference']['source'],'saved_place')
        self.monitor.address_resolver.assert_not_called()
        self.monitor.place_resolver=lambda *args:self.fail('Frozen message must not reread labels')
        with self.monitor.tracks.connect() as db:db.execute("UPDATE monitor_events SET delivery='pending'")
        self.assertEqual(self.send()[0],text)

    def test_charge_notification_uses_actual_saved_region_without_map_request(self):
        from unittest.mock import Mock
        from zeekr_control.notification_places import NotificationPlaces
        from zeekr_control.personal_store import PersonalStore
        store=PersonalStore(Path(self.temp.name)/'personal.sqlite3')
        store.change('owner','test-vehicle','place_names','save','named-garage',
            dict(name='我的车库',latitude=31,longitude=121,radius_m=150),0)
        service=NotificationPlaces(self.monitor.tracks.path,store)
        self.monitor.place_resolver=lambda vehicle,kind,data,identity:service.resolve('owner',vehicle,kind,data,identity)
        self.monitor.address_resolver=Mock()
        self.start_charge(trusted=True)
        text,data=self.send()
        self.assertIn('充电地点：我的车库附近（已标注充电地点',text)
        self.assertEqual(data['start_location_reference']['source'],'saved_charge_place')
        self.monitor.address_resolver.assert_not_called()

    def test_saved_label_qualifier_survives_small_report_budget(self):
        from zeekr_control.report_render import render
        self.start_charge()
        _,data=self.send()
        reference=dict(source='saved_charge_place',scope='single',label_only=True)
        for target in (1900,1100,300):
            text,_=render('charge_start',data['report_v2'],'synthetic',
                {'start':'我标注的充电站'},target=target,references={'start':reference})
            if '充电地点：' in text:self.assertIn('本次充电已确认，无可信定位',text)

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
        # Retry starts after preparation/send time, not exactly at entry + 60s.
        import math
        with self.monitor.tracks.connect() as db:
            retry_seconds=math.ceil((db.execute('SELECT next_attempt FROM monitor_events').fetchone()[0]-BASE)/1000)
        self.assertGreaterEqual(retry_seconds,660)
        self.record(590)
        self.monitor = Monitor(self.monitor.tracks.path)
        self.monitor.address_resolver = lambda location: self.fail('Frozen report must not re-resolve')
        text, data = self.send(retry_seconds)
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

    def test_commute_fallback_is_labeled_frozen_and_never_becomes_gps(self):
        calls=[]
        def resolve(vehicle, event):
            calls.append(event)
            return {'start': {'name':'家','reference':{'source':'commute_rule','rule_revision':1}}}
        self.monitor.commute_resolver=resolve
        self.start_charge()
        text,_=self.send()
        self.assertEqual(calls,[])
        self.assertIn('充电地点：位置未知',text)
        # A separate finished trip, with no trustworthy endpoint GPS.
        with self.monitor.tracks.connect() as db:
            db.execute('DELETE FROM monitor_events')
            db.execute('DELETE FROM monitor_state')
        for seconds,changes in ((900,dict(speed=30,engine='engine_on',ready=1)),(960,dict(km=110))):
            raw=sample(seconds,**changes);raw['position']['posCanBeTrusted']=False
            self.monitor.observe('test-vehicle',raw,BASE+seconds*1000)
        for seconds in range(1020,1561,60):
            raw=sample(seconds,km=110);raw['position']['posCanBeTrusted']=False
            self.monitor.observe('test-vehicle',raw,BASE+seconds*1000)
        text,data=self.send()
        self.assertIn('出发地：家附近（通勤规则推断，非精确起点）',text)
        self.assertIs(data['start_location']['trusted'],False)
        self.assertEqual(data['start_location_reference']['source'],'commute_rule')
        from zeekr_control.report_preview import preview
        self.assertIn('通勤规则推断',preview(database_path=self.monitor.tracks.path,event_id=self.monitor.events()[0]['id'])['text'])
        self.monitor.commute_resolver=lambda *args:self.fail('Frozen message must not rematch')
        with self.monitor.tracks.connect() as db:
            db.execute("UPDATE monitor_events SET delivery='pending'")
        repeated,_=self.send()
        self.assertEqual(repeated,text)

    def test_trusted_address_wins_over_commute_fallback(self):
        self.start_charge(trusted=True)
        self.monitor.commute_resolver=lambda *args:self.fail('Do not need fallback')
        with self.monitor.tracks.connect() as db:
            db.execute("UPDATE monitor_events SET kind='trip_end'")
        text,_=self.send()
        self.assertIn('出发地：浦东新区·测试园区附近',text)
        self.assertNotIn('规则推断',text)

    def test_finished_trip_resolves_from_real_shared_commute_decision(self):
        from unittest.mock import patch
        from zeekr_control.commute_tags import CommuteTags
        from zeekr_control.personal_store import PersonalStore
        commute=CommuteTags(PersonalStore(Path(self.temp.name)/'personal.sqlite3'),self.monitor.tracks.path)
        with patch('zeekr_control.commute_tags.time.time',return_value=BASE/1000-1):
            commute.update('owner','test-vehicle',dict(action='commute-save',revision=0,
                home=dict(latitude=31,longitude=121,radius_m=300),
                work=dict(latitude=31.01,longitude=121.01,radius_m=300)))
        self.monitor.commute_resolver=lambda vehicle,event:commute.notification_places('owner',vehicle,event)
        for seconds,changes in ((0,{}),(60,dict(speed=30,engine='engine_on',ready=1,km=101)),
                                (240,dict(km=110))):
            raw=sample(seconds,**changes);raw['position']['posCanBeTrusted']=False
            self.monitor.observe('test-vehicle',raw,BASE+seconds*1000)
        self.record(120)
        self.record(180,latitude=111636000,longitude=435636000)
        for seconds in range(300,841,60):
            raw=sample(seconds,km=110);raw['position']['posCanBeTrusted']=False
            self.monitor.observe('test-vehicle',raw,BASE+seconds*1000)
        self.monitor.address_resolver=None
        text,data=self.send(840)
        self.assertIn('出发地：家附近（通勤规则推断，非精确起点）',text)
        self.assertIn('到达地：公司附近（通勤规则推断，非精确终点）',text)
        self.assertIs(data['start_location']['trusted'],False)
        self.assertIs(data['end_location']['trusted'],False)

    def test_charge_end_references_charge_start_instead_of_stop_location(self):
        self.record(420)
        self.start_charge()
        self.monitor.observe('test-vehicle', sample(660), BASE + 660000)
        sent = []
        self.monitor.deliver(sent.append, BASE + 660000)
        self.assertEqual(len(sent), 2)
        self.assertTrue(all('参考位置，3分钟前可信定位' in text for text in sent))
