"""Observed AC power uses one synthetic snapshot, never residual DC voltage."""
import unittest

from test_ac_charging import ac_sample
from test_monitor import BASE
from zeekr_control.report_metrics import charge_metrics
from zeekr_control.report_telemetry import normalize


class AcPowerTests(unittest.TestCase):
    def test_ac_power_uses_same_observation_generic_voltage_and_current(self):
        for residual_voltage in (0, 360, 450):
            with self.subTest(residual_voltage=residual_voltage):
                point = normalize(ac_sample(dcChargePileUAct=residual_voltage), BASE)
                self.assertAlmostEqual(point['power_kw'], 3.52)
                self.assertEqual(point['power_source'], 'ac_ui')
                self.assertEqual(point['ac_voltage']['value'], 220)
                self.assertEqual(point['ac_current']['value'], 16)
                self.assertEqual(point['voltage']['value'], residual_voltage)
                self.assertEqual(point['current']['value'], 0)

    def test_unknown_zero_invalid_or_conflicting_ac_state_has_no_power(self):
        for changes in ({'chargerState': 99}, {'chargeIAct': 0}, {'chargeIAct': -1},
                        {'chargeIAct': None}, {'chargeIAct': True},
                        {'chargeIAct': 'invalid'}, {'chargeUAct': 0},
                        {'chargeUAct': None}, {'chargeUAct': float('inf')},
                        {'chargeUAct': 'invalid'}, {'dcChargePileIAct': 10},
                        {'ptReady': 1}):
            with self.subTest(changes=changes):
                point = normalize(ac_sample(**changes), BASE)
                self.assertIsNone(point['power_kw'])
                self.assertIsNone(point['power_source'])
        raw = ac_sample()
        raw['basicVehicleStatus'].update(speed=30, speedValidity=True)
        point = normalize(raw, BASE)
        self.assertIsNone(point['power_kw'])
        self.assertIsNone(point['power_source'])

    def test_dc_power_keeps_its_original_electrical_source(self):
        raw = ac_sample(chargerState=24, statusOfChargerConnection=0,
                        chargeLidAcStatus=2, chargeLidDcAcStatus=1,
                        dcChargeSts=12, dcChargePileUAct=400, dcChargePileIAct=100)
        point = normalize(raw, BASE)
        self.assertEqual(point['charging_mode'], 'dc')
        self.assertEqual(point['power_kw'], 40)
        self.assertEqual(point['power_source'], 'dc_pile_ui')
        self.assertEqual(point['ac_voltage']['value'], 220)
        self.assertEqual(point['ac_current']['value'], 16)

    def test_ac_average_is_time_weighted_and_excludes_final_stop_interval(self):
        points = [normalize(ac_sample(seconds, chargeIAct=current), BASE + seconds * 1000)
                  for seconds, current in ((0, 10), (60, 20), (180, 30), (240, 30))]
        points.append(normalize(ac_sample(300, chargeIAct=0, chargerState=0,
                                          statusOfChargerConnection=0), BASE + 300000))
        self.assertIs(points[-1]['charging'], False)
        self.assertIsNone(points[-1]['power_kw'])
        result = charge_metrics(points[0], points[-1], points, {'battery_capacity_kwh': 86})
        # Trapezoids: 3.3*60 + 5.5*120 + 6.6*60 = 1254 kW seconds.
        self.assertAlmostEqual(result['average_power_kw'], 1254 / 240)
        self.assertAlmostEqual(result['sampled_peak_kw'], 6.6)
        self.assertEqual(result['power_covered_seconds'], 240)
        self.assertEqual(result['charging_time_covered_seconds'], 240)
        self.assertAlmostEqual(result['power_coverage'], .8)

    def test_ac_unknown_current_breaks_power_coverage(self):
        points = [normalize(ac_sample(seconds, chargeIAct=current), BASE + seconds * 1000)
                  for seconds, current in ((0, 16), (60, 0), (120, 16), (180, 16), (240, 16))]
        points.append(normalize(ac_sample(300, chargeIAct=0, chargerState=0,
                                          statusOfChargerConnection=0), BASE + 300000))
        result = charge_metrics(points[0], points[-1], points, {})
        self.assertEqual(result['power_covered_seconds'], 120)
        self.assertAlmostEqual(result['power_coverage'], .4)
        self.assertIsNone(result['average_power_kw'])


if __name__ == '__main__':
    unittest.main()
