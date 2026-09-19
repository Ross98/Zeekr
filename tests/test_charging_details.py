import json
import unittest

from zeekr_control.report_telemetry import normalize


class ChargingDetailsTests(unittest.TestCase):
    def test_current_parameters_include_high_voltage_and_unknown_codes(self):
        from zeekr_control.charging_details import snapshot_details
        snapshot = normalize({'additionalVehicleStatus': {
            'chargeHvSts': 7, 'electricVehicleStatus': {
                'chargeUAct': 206.2, 'chargeIAct': 31.4,
                'chargeLidAcStatus': 1, 'bookChargeSts': 9,
                'timeToFullyCharged': 2047, 'secret': 'SECRET'}}}, 1000)
        rows = {row['key']: row for row in snapshot_details(snapshot)['parameters']}
        self.assertEqual(rows['chargeUAct']['value'], 206.2)
        self.assertEqual(rows['chargeHvSts']['value'], 7)
        self.assertEqual(rows['bookChargeSts']['value'], 9)
        self.assertIn('未确认', rows['bookChargeSts']['note'])
        self.assertIsNone(rows['timeToFullyCharged']['value'])
        self.assertNotIn('SECRET', json.dumps(snapshot))

    def test_history_projection_is_whitelisted_and_old_records_stay_missing(self):
        from zeekr_control.charging_details import history_details
        report = {'schema_version': 2, 'start': {'soc': 52, 'charging_mode': 'ac',
            'charging_parameters': {'chargeUAct': 206, 'bookChargeSts': {'secret': 'SECRET'}},
            'location': 'SECRET'}, 'end': {'soc': 90},
            'metrics': {'sampled_peak_kw': 6.5, 'average_power_kw': float('nan'),
                        'power_coverage': .8, 'address': 'SECRET'}, 'message': 'SECRET'}
        projected = history_details(report)
        self.assertEqual(projected['start']['mode'], 'ac')
        self.assertEqual(projected['metrics']['sampled_peak_kw'], 6.5)
        self.assertIsNone(projected['metrics']['average_power_kw'])
        self.assertNotIn('SECRET', json.dumps(projected))
        self.assertIsNone(history_details(None))
        self.assertIsNone(history_details({'schema_version': 99}))
        self.assertIsNone(history_details([]))
        self.assertIsNone(history_details({'schema_version': 2, 'start': [], 'end': {}}))

    def test_old_snapshot_uses_saved_metrics_not_current_vehicle(self):
        from zeekr_control.charging_details import snapshot_details
        rows = {r['key']: r for r in snapshot_details({
            'ac_voltage': {'value': 210, 'validity': 'valid'},
            'current': {'value': 0, 'validity': 'valid'}, 'ac_lid': 'closed'})['parameters']}
        self.assertEqual(rows['chargeUAct']['value'], 210)
        self.assertEqual(rows['dcChargePileIAct']['value'], 0)
        self.assertIsNone(rows['bookChargeSts']['value'])
        self.assertIsNone(rows['chargeLidAcStatus']['value'])
