"""Synthetic transition tests; no vehicle requests or real notifications."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

BASE = 1704067200000


def sample(seconds, speed=0, engine='engine_off', ready=0, soc=80, km=100,
           current=0, voltage=0, code=0, charger=0, plug=0, dc_lid=2):
    return {'updateTime': BASE + seconds * 1000,
            'basicVehicleStatus': {'speed': speed, 'speedValidity': True, 'engineStatus': engine},
            'position': {'latitude': 111600000, 'longitude': 435600000,
                         'posCanBeTrusted': True, 'marsCoordinates': False},
            'additionalVehicleStatus': {
                'maintenanceStatus': {'odometer': km},
                'electricVehicleStatus': {'ptReady': ready, 'chargeLevel': soc,
                    'chargeSts': code, 'chargerState': charger, 'statusOfChargerConnection': plug,
                    'chargeIAct': current, 'chargeUAct': voltage,
                    'chargeLidAcStatus': 2, 'chargeLidDcAcStatus': dc_lid}}}


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('zeekr_control.monitor'), '监控模块尚未实现')
        from zeekr_control.monitor import Monitor
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'private' / 'tracks.sqlite3'
        self.monitor = Monitor(self.path)

    def observe(self, seconds, **kwargs):
        return self.monitor.observe('test-vehicle', sample(seconds, **kwargs), BASE + seconds * 1000)

    def test_trip_waits_ten_minutes_freezes_endpoint_and_survives_restart(self):
        self.observe(0)
        self.observe(60, speed=30, engine='engine_on', ready=1, km=101)
        self.observe(120, km=110, soc=76)
        self.assertEqual(self.monitor.events(), [])
        from zeekr_control.monitor import Monitor
        self.monitor = Monitor(self.path)
        for t in range(180, 720, 60):
            self.observe(t, km=110, soc=79)
        self.assertEqual(self.monitor.events(), [])
        self.observe(720, km=110, soc=79)
        events = self.monitor.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'trip_end')
        self.assertEqual(events[0]['summary']['distance_km'], 10)
        self.assertEqual(events[0]['summary']['soc_delta'], -4)
        self.assertEqual(events[0]['summary']['duration_seconds'], 120)
        self.assertIn('kWh：暂无可靠数据', events[0]['message'])
        self.observe(780, km=110)
        self.assertEqual(len(self.monitor.events()), 1)
        self.assertGreater(self.monitor.tracks.day('test-vehicle', '2024-01-01')['count'], 0)

    def test_moving_again_cancels_stop_timer(self):
        self.observe(0, speed=20, engine='engine_on', ready=1)
        self.observe(60)
        self.observe(120, speed=30, engine='engine_on', ready=1, km=102)
        for t in range(180, 721, 60):
            self.observe(t, km=102)
        self.assertEqual(self.monitor.events(), [])
        self.observe(780, km=102)
        self.assertEqual(len(self.monitor.events()), 1)

    def test_old_duplicate_future_and_missing_time_do_not_end_trip(self):
        self.observe(0, speed=20, engine='engine_on', ready=1)
        self.observe(60)
        self.monitor.observe('test-vehicle', sample(60), BASE + 900000)
        self.monitor.observe('test-vehicle', sample(30), BASE + 900000)
        self.monitor.observe('test-vehicle', sample(1000), BASE + 900000)
        raw = sample(900)
        del raw['updateTime']
        self.monitor.observe('test-vehicle', raw, BASE + 900000)
        self.assertEqual(self.monitor.events(), [])
        self.observe(900)
        self.assertEqual(self.monitor.events(), [])

    def test_unknown_power_interrupts_stop_confirmation(self):
        self.observe(0, speed=20, engine='engine_on', ready=1)
        self.observe(60)
        for t in range(120, 721, 60):
            self.observe(t, engine='unknown', ready=None)
        self.observe(780)
        self.assertEqual(self.monitor.events(), [])

    def test_charge_begin_stop_and_restart_do_not_duplicate(self):
        self.observe(0)
        self.observe(60, soc=50, current=16, voltage=220, code='charging', dc_lid=1, charger=99, plug=1)
        self.observe(120, soc=51, current=16, voltage=220, code='charging', dc_lid=1, charger=99, plug=1)
        from zeekr_control.monitor import Monitor
        self.monitor = Monitor(self.path)
        self.observe(180, soc=53)
        events = self.monitor.events()
        self.assertEqual([e['kind'] for e in events], ['charge_start', 'charge_end'])
        self.assertEqual(events[1]['summary']['soc_delta'], 3)
        self.assertEqual(events[1]['summary']['duration_seconds'], 120)
        self.observe(240, soc=53)
        self.assertEqual(len(self.monitor.events()), 2)

    def test_plug_only_zero_current_and_unknown_codes_are_not_transitions(self):
        self.observe(0)
        self.observe(60, plug=1, code=7, charger=7)
        self.assertEqual(self.monitor.events(), [])
        self.observe(120, current=10, voltage=220, plug=1, code='charging', dc_lid=1, charger=7)
        self.observe(180, plug=1, code=7, charger=7)
        self.assertEqual([e['kind'] for e in self.monitor.events()], ['charge_start'])

    def test_first_observation_charging_marks_unknown_start(self):
        self.observe(0, current=10, voltage=220, plug=1, code='charging', dc_lid=1, charger=7)
        self.assertTrue(self.monitor.events()[0]['summary']['partial'])
        self.assertIn('开始时间未知', self.monitor.events()[0]['message'])

    def test_invalid_speed_and_low_voltage_soc_do_not_create_trip(self):
        raw = sample(0, speed=60)
        raw['basicVehicleStatus']['speedValidity'] = 'false'
        raw['additionalVehicleStatus']['electricVehicleStatus']['chargeLevel'] = None
        raw['additionalVehicleStatus']['maintenanceStatus']['mainBatteryStatus'] = {'chargeLevel': 99}
        self.monitor.observe('test-vehicle', raw, BASE)
        self.assertIsNone(self.monitor.status('test-vehicle')['trip'])

    def test_delivery_success_is_not_repeated_and_failures_back_off(self):
        from zeekr_control.notifications import DeliveryError
        self.observe(0)
        self.observe(60, current=10, voltage=220, plug=1, code='charging', dc_lid=1, charger=7)
        calls = []
        def failing(message):
            calls.append(message)
            raise DeliveryError('rejected', ambiguous=False)
        self.monitor.deliver(failing, BASE + 60000)
        self.monitor.deliver(failing, BASE + 61000)
        self.assertEqual(len(calls), 1)
        self.monitor.deliver(calls.append, BASE + 121000)
        self.monitor.deliver(calls.append, BASE + 180000)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.monitor.events()[0]['delivery'], 'sent')

    def test_uncertain_delivery_is_not_automatically_repeated(self):
        from zeekr_control.notifications import DeliveryError
        self.observe(0, current=10, voltage=220, plug=1, code='charging', dc_lid=1, charger=7)
        def timeout(message):
            raise DeliveryError('unknown', ambiguous=True)
        self.monitor.deliver(timeout, BASE)
        self.monitor.deliver(lambda message: self.fail('重复发送'), BASE + 3600000)
        self.assertEqual(self.monitor.events()[0]['delivery'], 'uncertain')

    def test_two_vehicles_keep_independent_state(self):
        self.observe(0, speed=20, engine='engine_on', ready=1)
        self.monitor.observe('other', sample(60), BASE + 60000)
        self.assertIsNotNone(self.monitor.status('test-vehicle')['trip'])
        self.assertIsNone(self.monitor.status('other')['trip'])

    def test_current_and_voltage_alone_do_not_confirm_charging(self):
        self.observe(0)
        self.observe(60, current=10, voltage=350, code=99, charger=99, plug=1)
        self.assertEqual(self.monitor.events(), [])

    def test_verified_dc_combination_includes_open_lid(self):
        from zeekr_control.monitor import decode
        raw = sample(0, code=0, charger=24, plug=0)
        electric = raw['additionalVehicleStatus']['electricVehicleStatus']
        electric.update(chargeLidAcStatus=2, chargeLidDcAcStatus=1, dcChargeSts=12,
                        dcChargeIAct=-200, dcChargePileUAct=380, dcChargePileIAct=210)
        self.assertIs(decode(raw)['charging'], True)
        raw['basicVehicleStatus']['speed'] = 30
        self.assertIsNone(decode(raw)['charging'])
        raw['basicVehicleStatus']['speed'] = 0
        for lid in (2, None, 99):
            electric['chargeLidDcAcStatus'] = lid
            self.assertIsNone(decode(raw)['charging'])

    def test_lid_open_or_pile_voltage_alone_does_not_confirm_charging(self):
        from zeekr_control.monitor import decode
        raw = sample(0, charger=24)
        electric = raw['additionalVehicleStatus']['electricVehicleStatus']
        electric.update(chargeLidDcAcStatus=1, dcChargeSts=12, dcChargePileUAct=380)
        for current in (None, 0, -200):
            electric['dcChargePileIAct'] = current
            self.assertIsNone(decode(raw)['charging'])

    def test_generic_idle_cannot_override_conflicting_dc_evidence(self):
        from zeekr_control.monitor import decode
        raw = sample(0)
        electric = raw['additionalVehicleStatus']['electricVehicleStatus']
        electric.update(chargeLidDcAcStatus=1, dcChargeSts=12,
                        dcChargePileUAct=380, dcChargePileIAct=210)
        self.assertIsNone(decode(raw)['charging'])

    def test_explicit_charge_status_cannot_ignore_closed_or_unknown_lid(self):
        from zeekr_control.monitor import decode
        raw = sample(0, code='charging', plug=1)
        electric = raw['additionalVehicleStatus']['electricVehicleStatus']
        electric.update(chargeLidAcStatus=2, chargeLidDcAcStatus=2)
        self.assertIsNone(decode(raw)['charging'])
        electric['chargeLidAcStatus'] = 1  # AC open code has not been verified.
        self.assertIsNone(decode(raw)['charging'])

    def test_explicit_stop_with_open_lid_is_allowed_without_active_dc_evidence(self):
        from zeekr_control.monitor import decode
        self.assertIs(decode(sample(0, code='stopped', dc_lid=1))['charging'], False)

    def test_invalid_dc_fields_do_not_fall_back_to_generic_idle(self):
        from zeekr_control.monitor import decode
        raw = sample(0)
        raw['additionalVehicleStatus']['electricVehicleStatus']['dcChargePileIAct'] = 'invalid'
        self.assertIsNone(decode(raw)['charging'])

    def test_dc_session_does_not_end_on_transient_zero_current(self):
        raw = sample(0, charger=24)
        electric = raw['additionalVehicleStatus']['electricVehicleStatus']
        electric.update(chargeLidDcAcStatus=1, dcChargeSts=12,
                        dcChargePileUAct=380, dcChargePileIAct=210)
        self.monitor.observe('test-vehicle', raw, BASE)
        raw['updateTime'] = BASE + 60000
        electric['dcChargePileIAct'] = 0
        self.monitor.observe('test-vehicle', raw, BASE + 60000)
        self.assertEqual([e['kind'] for e in self.monitor.events()], ['charge_start'])
        raw['updateTime'] = BASE + 120000
        electric.update(chargerState=0, dcChargeSts=0, chargeLidDcAcStatus=2)
        self.monitor.observe('test-vehicle', raw, BASE + 120000)
        self.assertEqual([e['kind'] for e in self.monitor.events()], ['charge_start', 'charge_end'])

    def test_driving_overrides_conflicting_charging_telemetry(self):
        for signal in ({'speed': 30}, {'engine': 'engine_on'}, {'ready': 1}):
            with self.subTest(signal=signal):
                from zeekr_control.monitor import decode
                point = decode(sample(0, current=10, voltage=350, code='charging', dc_lid=1, **signal))
                self.assertIsNone(point['charging'])

    def test_charging_during_short_stop_invalidates_combined_trip_energy(self):
        self.observe(0)
        self.observe(60, speed=20, engine='engine_on', ready=1)
        self.observe(120, soc=79)
        self.observe(180, soc=80, current=10, voltage=220, plug=1, code='charging', dc_lid=1, charger=7)
        self.observe(240, soc=81, speed=20, engine='engine_on', ready=1)
        for t in range(300, 901, 60):
            self.observe(t, soc=80)
        event = [e for e in self.monitor.events() if e['kind'] == 'trip_end'][0]
        self.assertIsNone(event['summary']['soc_delta'])

    def test_interrupted_sending_is_uncertain_after_restart(self):
        self.observe(0, current=10, voltage=220, plug=1, code='charging', dc_lid=1, charger=7)
        with self.monitor.tracks.connect() as db:
            db.execute("UPDATE monitor_events SET delivery='sending'")
        from zeekr_control.monitor import Monitor
        self.monitor = Monitor(self.path)
        self.monitor.deliver(lambda message: self.fail('不应重发'), BASE + 60000)
        self.assertEqual(self.monitor.events()[0]['delivery'], 'uncertain')

    def test_charging_after_final_stop_does_not_change_trip_energy(self):
        self.observe(0)
        self.observe(60, speed=20, engine='engine_on', ready=1)
        self.observe(120, soc=76)
        for t in range(180, 721, 60):
            self.observe(t, soc=80, current=10, voltage=220, plug=1, code='charging', dc_lid=1, charger=7)
        event = [e for e in self.monitor.events() if e['kind'] == 'trip_end'][0]
        self.assertEqual(event['summary']['soc_delta'], -4)


class EstimatedEnergyTests(unittest.TestCase):
    def test_charge_and_trip_estimates_are_labelled(self):
        from zeekr_control.monitor import message_for
        data = dict(start_time=BASE, end_time=BASE+60000, duration_seconds=60,
                    distance_km=9, start_soc=48, end_soc=90, soc_delta=42,
                    partial=False, battery_capacity_kwh=86)
        self.assertIn('估算充入电量：36.1 kWh', message_for('charge_end', data, 'test'))
        data.update(start_soc=90, end_soc=88, soc_delta=-2)
        self.assertIn('估算耗电量：1.7 kWh', message_for('trip_end', data, 'test'))
        for changes in ({'soc_delta': None}, {'battery_capacity_kwh': None},
                        {'soc_delta': 2}, {'start_soc': None}):
            invalid = dict(data, **changes)
            self.assertNotIn('估算耗电量：', message_for('trip_end', invalid, 'test'))


if __name__ == '__main__':
    unittest.main()


class LocationNotificationTests(unittest.TestCase):
    setUp = MonitorTests.setUp
    observe = MonitorTests.observe

    def test_trip_addresses_use_frozen_endpoints_and_persist_for_retry(self):
        from zeekr_control.monitor import Monitor
        self.observe(0)
        self.observe(60, speed=30, engine='engine_on', ready=1, km=101)
        raw = sample(120, km=110)
        raw['position']['longitude'] = 432000000
        self.monitor.observe('test-vehicle', raw, BASE + 120000)
        self.monitor = Monitor(self.path)
        for t in range(180, 721, 60):
            self.observe(t, km=110)
        calls = []
        def resolve(location):
            calls.append(location['longitude'])
            return {121.0: '上海市测试起点', 120.0: '江苏省测试终点'}[location['longitude']]
        self.monitor.address_resolver = resolve
        from zeekr_control.notifications import DeliveryError
        def reject(message):
            raise DeliveryError('retry')
        self.monitor.deliver(reject, BASE + 720000)
        sent = []
        self.monitor.deliver(sent.append, BASE + 800000)
        self.assertEqual(calls, [121.0, 120.0])
        self.assertIn('出发地：上海市测试起点', sent[0])
        self.assertIn('到达地：江苏省测试终点', sent[0])
        self.assertNotIn('121.0', sent[0])

    def test_charge_uses_start_location_and_missing_location_does_not_block_send(self):
        self.observe(0)
        self.observe(60, code='charging', dc_lid=1)
        self.observe(120)
        self.monitor.address_resolver = lambda location: '上海市测试充电站' if location else None
        sent = []
        self.monitor.deliver(sent.append, BASE + 120000)
        self.assertEqual(len(sent), 2)
        self.assertTrue(all('充电地点：上海市测试充电站' in m for m in sent))
        from zeekr_control.monitor import message_for
        data = self.monitor.events()[1]['summary']
        data.pop('start_address', None)
        self.assertIn('充电地点：位置未知', message_for('charge_end', data, 'test'))
