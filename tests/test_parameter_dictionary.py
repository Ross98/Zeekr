"""Dictionary presentation never replaces live values or calibrated decoders."""
import unittest
from zeekr_control.web_model import build_model


class ParameterDictionaryTests(unittest.TestCase):
    def test_platform_fields_explain_applicability_without_changing_values(self):
        model = build_model({'additionalVehicleStatus': {
            'runningStatus': {'fuelLevelPct': '0', 'engineCoolantLevelStatus': '3'},
            'drivingSafetyStatus': {'seatBeltStatusThDriverRear': 'false'},
            'trailerStatus': {'trailerBreakLampSts': '0'}}})
        fields = {f['key']: f for f in model['fields']}
        self.assertIn('纯电 001 通常不适用', fields['fuelLevelPct']['reference']['applicability'])
        self.assertIn('第三排', fields['seatBeltStatusThDriverRear']['reference']['applicability'])
        self.assertIn('配置', fields['trailerBreakLampSts']['reference']['applicability'])
        self.assertIn('不能据此判定', fields['engineCoolantLevelStatus']['reference']['applicability'])
        self.assertEqual(fields['fuelLevelPct']['value'], '0')
        self.assertEqual(fields['fuelLevelPct']['evidence'], '待核实')

    def test_contextual_names_and_live_values(self):
        model = build_model({'additionalVehicleStatus': {
            'electricVehicleStatus': {'chargeLevel': '42'},
            'maintenanceStatus': {'mainBatteryStatus': {'chargeLevel': '91', 'stateOfHealth': '0'}},
            'runningStatus': {'afs': '7'}}})
        fields = {f['path']: f for f in model['fields']}
        battery = fields['additionalVehicleStatus.electricVehicleStatus.chargeLevel']
        aux = fields['additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.chargeLevel']
        self.assertIn('动力电池', battery['name'])
        self.assertIn('低压辅助电池', aux['name'])
        self.assertEqual(battery['raw'], '42')
        afs = fields['additionalVehicleStatus.runningStatus.afs']
        self.assertIn('推测', afs['name'])
        self.assertEqual(afs['value'], '7')
        self.assertEqual(afs['evidence'], '待核实')
        self.assertIn('hella.com', str(afs['reference']['sources']))
        self.assertNotIn('raw', battery['reference'])
        self.assertNotIn('86%', str(battery['reference']))

    def test_known_extra_fields_no_unknown_path_or_identity_leak(self):
        model = build_model({'configuration': {'vin': 'SECRET-VIN'},
            'basicVehicleStatus': {'position': {'latitude': 'SECRET-LAT', 'longitude': 'SECRET-LON',
                'posCanBeTrusted': 'true', 'altitude': '777'}},
            'temStatus': {'imei': 'SECRET-IMEI', 'swVersion': None,
                'backupBattery': {'voltage': '3.1'}},
            'untrusted': {'chargeLevel': 'SECRET-INJECTED'},
            'additionalVehicleStatus': {'trailerStatus': {'trailerBreakLampSts': '3'}}})
        self.assertNotIn('SECRET', str(model))
        fields = {f['path']: f for f in model['fields']}
        self.assertEqual(fields['basicVehicleStatus.position.posCanBeTrusted']['raw'], 'true')
        self.assertIn('备用电池', fields['temStatus.backupBattery.voltage']['name'])
        self.assertEqual(fields['temStatus.swVersion']['value'], '未知')
        self.assertIn('制动灯', fields['additionalVehicleStatus.trailerStatus.trailerBreakLampSts']['name'])

    def test_metadata_is_separate_and_private_fields_never_exposed(self):
        model = build_model({'updateTime': 1704067200000}, vehicle={
            'modelName': 'TEST-MODEL', 'vin': 'SECRET-VIN', 'plateNo': 'SECRET-PLATE',
            'loginInfo': {'loginUid': 'SECRET-USER', 'isLogined': True},
            'vehiclePhotoSmall': 'https://example.com/SECRET-PHOTO',
            'updateTime': '2026-01-01', 'unknown': {'modelName': 'SECRET-INJECTED'}})
        self.assertNotIn('SECRET', str(model))
        fields = {f['path']: f for f in model['fields']}
        self.assertEqual(fields['vehicleMetadata.modelName']['raw'], 'TEST-MODEL')
        self.assertEqual(fields['vehicleMetadata.modelName']['group'], '车辆档案')
        self.assertEqual(fields['vehicleMetadata.updateTime']['raw'], '2026-01-01')

    def test_references_do_not_freeze_snapshot_conditions(self):
        model = build_model({'basicVehicleStatus': {'speed': '55', 'speedValidity': True},
            'additionalVehicleStatus': {'electricVehicleStatus': {'dcChargePileUAct': '401'},
                'climateStatus': {'sunroofPos': '50'}, 'maintenanceStatus': {'mainBatteryStatus': {'voltage': '12'}}}})
        for f in model['fields']:
            reference = str(f['reference'])
            for stale in ('本次展示解释', '当前 speedValidity=false', '397.2', '12:12:02', '2026-09-18 12:12'):
                self.assertNotIn(stale, reference)
        self.assertEqual(model['metrics']['battery'], '未知')

    def test_dictionary_exposes_structured_kinds_for_confirmation_scope(self):
        model = build_model({'updateTime': 1704067200000, 'basicVehicleStatus': {
            'speed': 12, 'speedValidity': True, 'engineStatus': 'engine_running'},
            'additionalVehicleStatus': {'electricVehicleStatus': {'chargeLevel': 42,
                'chargerState': 24}, 'climateStatus': {'temperatureUpdateTime': 1704067200000}}})
        fields = {field['path']: field for field in model['fields']}
        self.assertEqual(fields['additionalVehicleStatus.electricVehicleStatus.chargeLevel']['reference']['kind'], 'number')
        self.assertEqual(fields['basicVehicleStatus.speedValidity']['reference']['kind'], 'boolean')
        self.assertEqual(fields['basicVehicleStatus.engineStatus']['reference']['kind'], 'enum')
        self.assertEqual(fields['additionalVehicleStatus.climateStatus.temperatureUpdateTime']['reference']['kind'], 'timestamp')
