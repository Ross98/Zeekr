"""Startup placeholders must never become durations, including old reports."""
import unittest

from zeekr_control.charging_details import snapshot_details, history_details
from zeekr_control.report_telemetry import normalize
from zeekr_control.report_render import render
from zeekr_control.web_model import build_model
from zeekr_control.vehicle_parameters import parameters


BASE = 1790000000000
PATH = 'additionalVehicleStatus.electricVehicleStatus.timeToFullyCharged'


def payload(minutes):
    return {'basicVehicleStatus': {'engineStatus': 'engine_off', 'speed': 0,
                                  'speedValidity': True},
            'additionalVehicleStatus': {'electricVehicleStatus': {
                'ptReady': 0, 'chargeSts': 0, 'chargerState': 24,
                'statusOfChargerConnection': 0, 'chargeLidDcAcStatus': 1,
                'dcChargeSts': 12, 'dcChargePileUAct': 380,
                'dcChargePileIAct': 210, 'timeToFullyCharged': minutes}}}


def time_row(snapshot):
    return next(r for r in snapshot_details(snapshot)['parameters']
                if r['key'] == 'timeToFullyCharged')


class ChargeTimeEstimateTests(unittest.TestCase):
    def test_startup_code_is_unavailable_without_hiding_raw_or_charging(self):
        raw = payload('2046')
        snapshot = normalize(raw, BASE)
        self.assertTrue(snapshot['charging'])
        self.assertEqual(snapshot['charging_parameters']['timeToFullyCharged'], 2046)
        self.assertIsNone(snapshot['remaining_minutes'])
        model = build_model(raw)
        self.assertEqual(model['charging']['remaining_time'], '暂不可用')
        field = next(f for f in model['fields'] if f['path'] == PATH)
        self.assertEqual(field['raw'], '2046')
        self.assertEqual(field['value'], '暂不可用')
        parameter = next(f for f in parameters(raw, model)['fields'] if f['path'] == PATH)
        self.assertIn('2046', parameter['raw'])
        self.assertEqual(parameter['value'], '暂不可用')
        self.assertEqual(parameter['status'], 'pending')
        self.assertEqual(parameter['value_validity'], 'suspect')
        self.assertNotIn('2046 分钟', str(model))

    def test_legacy_details_filter_saved_and_fallback_placeholders(self):
        for code in (2046, 2047):
            for snapshot in ({'charging': True, 'remaining_minutes': code},
                             {'charging': True, 'remaining_minutes': 20,
                              'charging_parameters': {'timeToFullyCharged': code}}):
                with self.subTest(snapshot=snapshot):
                    self.assertIsNone(time_row(snapshot)['value'])
                    self.assertIn('暂不可用', time_row(snapshot)['note'])
                    report = {'schema_version': 2, 'start': snapshot, 'end': snapshot}
                    details = history_details(report)
                    for side in ('start', 'end'):
                        self.assertIsNone(next(r for r in details[side]['parameters']
                            if r['key'] == 'timeToFullyCharged')['value'])

    def test_normal_values_including_zero_survive_and_estimates_can_recover(self):
        for code in (0, 7, 80, 2045):
            with self.subTest(code=code):
                snapshot = normalize(payload(code), BASE)
                self.assertEqual(snapshot['remaining_minutes'], code)
                self.assertEqual(time_row(snapshot)['value'], code)
                self.assertEqual(build_model(payload(code))['charging']['remaining_time'],
                                 str(code) + ' 分钟')
        for code in (2047, 2046, 2046, 33):
            self.assertEqual(normalize(payload(code), BASE)['remaining_minutes'],
                             33 if code == 33 else None)

    def test_legacy_notification_does_not_calculate_end_from_placeholders(self):
        for code in (2046, 2047):
            start = {'state_time': BASE, 'observed_at': BASE, 'soc': 50,
                     'remaining_minutes': code}
            report = {'start_time': BASE, 'start': start, 'partial': False,
                      'event_created_at': BASE}
            text, _ = render('charge_start', report, 'synthetic-time')
            self.assertNotIn('车辆估计剩余', text)
            self.assertNotIn('按本次估计约', text)

    def test_noncharging_and_invalid_estimates_stay_unavailable(self):
        for code in (None, True, -1, 2048, float('nan')):
            self.assertIsNone(normalize(payload(code), BASE)['remaining_minutes'])
        self.assertIsNone(time_row({'charging': False, 'remaining_minutes': 8})['value'])
