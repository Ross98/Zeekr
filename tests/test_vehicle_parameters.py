"""Full vehicle parameter projection uses synthetic data only."""
import json
import unittest
from unittest.mock import patch

from zeekr_control.parameter_dictionary import FIELDS
from zeekr_control.web_model import build_model


class VehicleParameterTests(unittest.TestCase):
    def project(self, raw=None, vehicle=None):
        from zeekr_control.vehicle_parameters import parameters
        return parameters(raw, build_model(raw or {}, vehicle) if raw is not None else None)

    def row(self, result, suffix):
        return next(row for row in result['fields'] if row['path'].endswith(suffix))

    def test_complete_catalog_without_private_fields_and_no_snapshot(self):
        result = self.project()
        expected = {path for path, entry in FIELDS.items() if not entry['private']}
        self.assertEqual({r['path'] for r in result['fields']}, expected)
        self.assertEqual(len(result['fields']), len(expected))
        self.assertEqual(result['counts']['total'], 217)
        self.assertEqual(result['counts']['missing'], 217)
        self.assertEqual(len(result['groups']), 14)
        self.assertFalse(result['has_snapshot'])

    def test_missing_null_invalid_pending_and_zero_are_distinct(self):
        result = self.project({'additionalVehicleStatus': {
            'climateStatus': {'interiorTemp': None, 'exteriorTemp': 'NaN', 'sunroofPos': 101},
            'electricVehicleStatus': {'chargeLevel': 0},
            'pollutionStatus': {'interiorPM25': 0}}})
        for suffix, status in [('interiorTemp', 'empty'), ('exteriorTemp', 'invalid'),
                               ('sunroofPos', 'pending'), ('electricVehicleStatus.chargeLevel', 'known'),
                               ('tyreStatusDriver', 'missing')]:
            self.assertEqual(self.row(result, suffix)['status'], status, suffix)
        self.assertEqual(self.row(result, 'interiorTemp')['raw'], 'null')
        self.assertEqual(self.row(result, 'electricVehicleStatus.chargeLevel')['value'], '0%')
        self.assertEqual(self.row(result, 'interiorPM25')['raw'], '0')
        self.assertNotEqual(self.row(result, 'interiorPM25')['status'], 'missing')
        self.assertEqual(result['counts']['returned'], 5)

    def test_number_bounds_bad_types_and_nonfinite_do_not_become_states(self):
        for value in (-1, 'NaN', float('inf'), True, '', {'secret': 'DO-NOT-EXPOSE'}, ['PRIVATE']):
            result = self.project({'additionalVehicleStatus': {'electricVehicleStatus': {'chargeLevel': value}}})
            row = self.row(result, 'electricVehicleStatus.chargeLevel')
            self.assertEqual(row['status'], 'invalid', repr(value))
            self.assertNotIn('DO-NOT-EXPOSE', json.dumps(result))
            self.assertNotIn('PRIVATE', json.dumps(result))
            json.dumps(result, allow_nan=False)

    def test_unverified_hood_and_lights_keep_raw_without_guessed_closed_state(self):
        result = self.project({'additionalVehicleStatus': {'drivingSafetyStatus': {'engineHoodOpenStatus': 0},
                                                          'runningStatus': {'loBeam': 0}}})
        for suffix in ('engineHoodOpenStatus', 'loBeam'):
            row = self.row(result, suffix)
            self.assertEqual(row['status'], 'pending')
            self.assertEqual(row['raw'], '0')
            self.assertNotIn('关闭', row['value'])

    def test_metadata_and_battery_paths_do_not_collide(self):
        result = self.project({'additionalVehicleStatus': {
            'electricVehicleStatus': {'chargeLevel': 64},
            'maintenanceStatus': {'mainBatteryStatus': {'chargeLevel': 97}}}},
            {'vin': 'HIDDEN-IDENTITY', 'modelName': 'SYNTHETIC-MODEL'})
        fields = {r['path']: r for r in result['fields']}
        self.assertEqual(fields['additionalVehicleStatus.electricVehicleStatus.chargeLevel']['raw'], '64')
        self.assertEqual(fields['additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.chargeLevel']['raw'], '97')
        self.assertNotIn('HIDDEN-IDENTITY', json.dumps(result))
        self.assertTrue(all(r['updated_time'] is None for r in result['fields'] if r['group'] == '车辆档案'))

    def test_metadata_preserves_null_and_scalar_types(self):
        for value, raw, status in [(None, 'null', 'empty'), ('0', '"0"', 'pending'), (0, '0', 'pending')]:
            row = self.row(self.project({}, {'modelName': value}), 'vehicleMetadata.modelName')
            self.assertEqual(row['raw'], raw)
            self.assertEqual(row['status'], status)

    def test_temperature_time_is_separate_and_no_independent_pm_time_invented(self):
        result = self.project({'updateTime': 1704067200000, 'additionalVehicleStatus': {
            'climateStatus': {'interiorTemp': 25, 'temperatureUpdateTime': 1704060000000},
            'pollutionStatus': {'interiorPM25': 15}}})
        self.assertEqual(self.row(result, 'interiorTemp')['updated_time'], 1704060000000)
        pm = self.row(result, 'interiorPM25')
        self.assertEqual(pm['updated_time'], 1704067200000)
        self.assertIn('独立更新时间未提供', pm['time_source'])

    def test_allowlist_filters_private_and_undocumented_payloads(self):
        result = self.project({'vin': 'SENSITIVE-VIN', 'accessToken': 'SENSITIVE-TOKEN',
            'basicVehicleStatus': {'position': {'latitude': 'PRIVATE-LAT', 'longitude': 'PRIVATE-LON'}},
            'additionalVehicleStatus': {'surprise': {'credential': 'SENSITIVE-UNKNOWN'}}})
        rendered = json.dumps(result)
        for token in ('SENSITIVE-', 'PRIVATE-LAT', 'PRIVATE-LON', 'latitude', 'longitude'):
            self.assertNotIn(token, rendered)

    def test_returned_counts_partition_catalog_and_keep_safe_future_fields(self):
        added = 'additionalVehicleStatus.futureStatus.extraCounter'
        entry = dict(FIELDS['basicVehicleStatus.usageMode'], name='未来安全字段', private=False)
        with patch.dict(FIELDS, {added: entry}):
            result = self.project({'additionalVehicleStatus': {'futureStatus': {'extraCounter': 5}}})
        row = next(r for r in result['fields'] if r['path'] == added)
        self.assertEqual(row['group'], '平台配置与其他')
        counts = result['counts']
        self.assertEqual(sum(counts[k] for k in ('known','pending','empty','invalid','missing')), counts['total'])
        self.assertEqual(counts['returned'], counts['total'] - counts['missing'])

    def test_text_is_bounded_and_never_interpreted_as_markup(self):
        result = self.project({'temStatus': {'swVersion': '<script>alert(1)</script>' + 'x' * 1000}})
        row = self.row(result, 'temStatus.swVersion')
        self.assertLessEqual(len(row['raw']), 140)
        self.assertEqual(row['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
