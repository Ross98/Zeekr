"""Offline tests: identifiers and observations are synthetic, never owner records."""
import importlib.util
import unittest


class WebModelTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('zeekr_control.web_model'), 'Web 展示模型尚未实现')
        from zeekr_control.web_model import build_model, parse_location
        self.build = build_model
        self.location = parse_location

    def test_battery_separation_unknown_enums_and_private_data(self):
        model = self.build({'vin': 'PRIVATE', 'updateTime': 1704067200000,
            'additionalVehicleStatus': {
                'electricVehicleStatus': {'chargeLevel': 62, 'timeToFullyCharged': 2047},
                'maintenanceStatus': {'mainBatteryStatus': {'chargeLevel': 98}},
                'drivingSafetyStatus': {'centralLockingStatus': 3, 'ownerName': 'PRIVATE'},
                'climateStatus': {'interiorTemp': None, 'sunroofPos': 101}}})
        self.assertEqual(model['metrics']['battery'], '62%')
        self.assertEqual(model['metrics']['inside'], '未知')
        self.assertNotIn('PRIVATE', str(model))
        self.assertEqual(model['lock']['value'], '未知')
        rows = {r['key']: r for r in model['fields']}
        self.assertEqual(rows['timeToFullyCharged']['value'], '暂无有效时间估计')
        self.assertNotIn('%', rows['sunroofPos']['value'])

    def test_dc_charging_is_shared_with_monitor_and_remaining_time_has_minutes(self):
        from zeekr_control.monitor import decode
        data = {'basicVehicleStatus': {'speed': 0, 'speedValidity': True, 'engineStatus': 'engine_off'},
                'additionalVehicleStatus': {'electricVehicleStatus': {
                    'ptReady': 0, 'chargeSts': 0, 'chargerState': 24, 'statusOfChargerConnection': 0,
                    'chargeLidDcAcStatus': 1, 'dcChargeSts': 12,
                    'dcChargePileUAct': 380, 'dcChargePileIAct': 210, 'timeToFullyCharged': 8}}}
        model = self.build(data)
        self.assertTrue(decode(data)['charging'])
        self.assertEqual(model['charging']['value'], '直流充电中')
        self.assertTrue(model['charging']['confirmed'])
        self.assertEqual(model['charging']['remaining_time'], '8 分钟')
        data['basicVehicleStatus']['speed'] = 30
        self.assertFalse(self.build(data)['charging']['confirmed'])
        self.assertEqual(self.build(data)['charging']['remaining_time'], '未知')

    def test_generic_idle_with_dc_conflict_is_unknown_in_web(self):
        data = {'additionalVehicleStatus': {'electricVehicleStatus': {
            'chargeSts': 0, 'chargerState': 0, 'statusOfChargerConnection': 0,
            'dcChargeSts': 12, 'dcChargePileUAct': 380, 'dcChargePileIAct': 210}}}
        self.assertFalse(self.build(data)['charging']['confirmed'])

    def test_all_doors_windows_and_combination_required(self):
        safety = {'centralLockingStatus': 2}
        climate = {}
        for side in ('Driver', 'Passenger', 'DriverRear', 'PassengerRear'):
            safety['doorLockStatus' + side] = 1
            safety['doorOpenStatus' + side] = 0
            climate['winPos' + side] = 0
        data = {'additionalVehicleStatus': {'drivingSafetyStatus': safety, 'climateStatus': climate}}
        model = self.build(data)
        self.assertEqual([x['name'] for x in model['doors']], ['左前', '右前', '左后', '右后'])
        self.assertTrue(all(x['lock'] == '已锁' and x['door'] == '关闭' and x['window'] == '关闭' for x in model['doors']))
        safety['doorLockStatusPassengerRear'] = None
        self.assertEqual(self.build(data)['lock']['value'], '未知')

    def test_location_scaling_does_not_invent_gps_time_or_trust(self):
        result = self.location({'updateTime': 1704067200000, 'position': {
            'latitude': 111600000, 'longitude': 435600000,
            'marsCoordinates': False, 'posCanBeTrusted': False}})
        self.assertEqual(result['latitude'], 31)
        self.assertEqual(result['longitude'], 121)
        self.assertFalse(result['trusted'])
        self.assertIsNone(result['gps_time'])
        self.assertEqual(result['coordinate_system'], 'WGS84（社区解释）')

    def test_invalid_location_not_plotted_and_missing_crs_not_assumed(self):
        for value in (None, True, 'NaN', 999999999999):
            self.assertFalse(self.location({'position': {'latitude': value, 'longitude': 435600000}})['valid'])
        result = self.location({'position': {'latitude': 111600000, 'longitude': 435600000}})
        self.assertFalse(result['plottable'])

    def test_temperature_has_independent_timestamp_and_no_position_leak(self):
        model = self.build({'updateTime': 1704067200000, 'position': {'latitude': 111600000},
            'additionalVehicleStatus': {'climateStatus': {'temperatureUpdateTime': 1704064080042}}})
        self.assertNotEqual(model['updated_at'], model['temperature_updated_at'])
        self.assertNotIn('111600000', str(model))

    def test_real_gw2_string_booleans_and_nested_position(self):
        data = {'basicVehicleStatus': {'position': {'latitude': '111600000',
                'longitude': '435600000', 'marsCoordinates': 'false', 'posCanBeTrusted': 'false'}}}
        result = self.location(data)
        self.assertTrue(result['plottable'])
        self.assertFalse(result['trusted'])
        data['basicVehicleStatus']['position']['posCanBeTrusted'] = 'true'
        self.assertTrue(self.location(data)['trusted'])

    def test_degree_coordinates_not_mistaken_for_scaled_integers(self):
        for latitude, longitude in ((31.2, 121.5), (31, 121)):
            result = self.location({'position': {'latitude': latitude, 'longitude': longitude,
                                                'marsCoordinates': False}})
            self.assertFalse(result['plottable'])

    def test_structured_metrics_keep_units_validation_and_independent_times(self):
        model = self.build({'updateTime': 1704067200000, 'additionalVehicleStatus': {
            'electricVehicleStatus': {'chargeLevel': '48', 'distanceToEmptyOnBatteryOnly': -1},
            'climateStatus': {'interiorTemp': 33.2, 'temperatureUpdateTime': 1704064080042}}})
        self.assertEqual(model.get('updated_time'), 1704067200000)
        metrics = model.get('metric_details', {})
        self.assertEqual(metrics.get('battery'), {'value': 48.0, 'unit': '%', 'updated_time': 1704067200000, 'evidence': '已返回'})
        self.assertIsNone(metrics['range']['value'])
        self.assertEqual(metrics['range']['evidence'], '未知')
        self.assertEqual(metrics['inside']['updated_time'], 1704064080042)
        self.assertIsNone(self.build({'updateTime': 'NaN'}).get('updated_time'))

    def test_summary_never_infers_open_or_closed_from_incomplete_combination(self):
        model = self.build({'additionalVehicleStatus': {'drivingSafetyStatus': {
            'doorOpenStatusDriver': 0, 'trunkOpenStatus': 0}}})
        self.assertEqual(model.get('closure'), {'doors': '未知', 'windows': '未知', 'trunk': '关闭'})
