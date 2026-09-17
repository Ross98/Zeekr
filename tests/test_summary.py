"""Offline tests: identifiers and observations are synthetic, never owner records."""
import unittest
from zeekr_control.summary import format_status


class SummaryTests(unittest.TestCase):
    def test_traction_fields_win_over_generic_and_low_voltage_battery(self):
        data = {
            'updateTime': '1704067200000',
            'basicVehicleStatus': {'distanceToEmpty': '0'},
            'additionalVehicleStatus': {
                'maintenanceStatus': {'odometer': '12560.000', 'mainBatteryStatus': {'chargeLevel': '96.5'}},
                'electricVehicleStatus': {'chargeLevel': '64', 'distanceToEmptyOnBatteryOnly': '302'},
                'climateStatus': {'interiorTemp': '25.6', 'exteriorTemp': '23.1'},
            },
        }
        text = format_status(data)
        for expected in ('64%', '302 km', '12,560 km', '25.6°C', '23.1°C', '2024-01-01 08:00:00'):
            self.assertIn(expected, text)
        self.assertNotIn('96.5', text)

    def test_missing_invalid_or_nonfinite_values_are_unknown(self):
        data = {'updateTime': 'NaN', 'additionalVehicleStatus': {
            'electricVehicleStatus': {'chargeLevel': '101', 'distanceToEmptyOnBatteryOnly': '-1'},
            'maintenanceStatus': {'odometer': 'Infinity'},
            'climateStatus': {'interiorTemp': True},
        }}
        text = format_status(data)
        self.assertIn('动力电池：未知', text)
        self.assertIn('电池续航：未知', text)
        self.assertIn('总里程：未知', text)
        self.assertIn('车内温度：未知', text)
        self.assertIn('更新时间：未知', text)

    def test_zero_is_valid_and_hidden_sections_not_treated_as_dicts(self):
        text = format_status({'additionalVehicleStatus': {
            'electricVehicleStatus': {'chargeLevel': '0', 'distanceToEmptyOnBatteryOnly': 0},
            'drivingSafetyStatus': '[hidden]', 'climateStatus': None,
        }})
        self.assertIn('动力电池：0%', text)
        self.assertIn('电池续航：0 km', text)
        self.assertIn('门锁：未知', text)

    def test_unverified_enums_and_units_not_invented(self):
        text = format_status({'additionalVehicleStatus': {
            'electricVehicleStatus': {'chargeSts': '0', 'timeToFullyCharged': '2047'},
            'climateStatus': {'winPosDriver': '0', 'sunroofPos': '101'},
            'maintenanceStatus': {'tyreStatusDriver': '265.125'},
            'drivingSafetyStatus': {'centralLockingStatus': '1'},
        }})
        self.assertIn('充电状态=0', text)
        self.assertIn('左前 265.125 kPa', text)
        self.assertIn('中控锁状态=1', text)
        for misleading in ('已锁', '未充电', '2047 分钟', '101%'):
            self.assertNotIn(misleading, text)

    def test_summary_never_dumps_unknown_private_fields(self):
        text = format_status({'vin': 'PRIVATE-VIN', 'additionalVehicleStatus': {
            'drivingSafetyStatus': {'ownerName': 'PRIVATE-NAME', 'other': 'PRIVATE-VALUE'},
        }})
        self.assertNotIn('PRIVATE', text)

    def test_confirmed_parked_combination_is_translated(self):
        safety = {'centralLockingStatus': '2', 'trunkOpenStatus': '0'}
        climate = {}
        for side in ('Driver', 'Passenger', 'DriverRear', 'PassengerRear'):
            safety['doorLockStatus' + side] = '1'
            safety['doorOpenStatus' + side] = '0'
            climate['winPos' + side] = '0'
        text = format_status({'additionalVehicleStatus': {
            'drivingSafetyStatus': safety, 'climateStatus': climate,
            'electricVehicleStatus': {'chargeSts': '0', 'chargerState': '0', 'statusOfChargerConnection': '0'},
        }})
        for expected in ('门锁：中控锁已锁', '充电：未充电', '车门：左前门关闭', '尾门：关闭', '车窗：左前窗关闭'):
            self.assertIn(expected, text)
        for position in ('左前', '右前', '左后', '右后'):
            for state in ('门已锁', '门关闭', '窗关闭'):
                self.assertIn(position + state, text)
        self.assertIn('充电状态：未充电', text)
        self.assertIn('充电器工作状态：0（原值，含义待核对）', text)
        self.assertIn('充电枪连接状态：0（原值，含义待核对）', text)
        self.assertNotIn('未插枪', text)

    def test_missing_or_conflicting_lock_does_not_claim_locked(self):
        for other in (None, '0', '3', True):
            safety = {'centralLockingStatus': '2', 'doorLockStatusDriver': '1',
                      'doorLockStatusPassenger': '1', 'doorLockStatusDriverRear': '1',
                      'doorLockStatusPassengerRear': other}
            text = format_status({'additionalVehicleStatus': {'drivingSafetyStatus': safety}})
            self.assertNotIn('门锁：已锁车', text)
            self.assertIn('门锁：未知', text)

    def test_unknown_window_code_does_not_claim_closed(self):
        text = format_status({'additionalVehicleStatus': {'climateStatus': {
            'winPosDriver': '0', 'winPosPassenger': '0',
            'winPosDriverRear': '0', 'winPosPassengerRear': '101'}}})
        self.assertNotIn('四窗关闭', text)
        self.assertIn('车窗：未知', text)

    def test_tyres_have_confirmed_positions_and_preserve_precision(self):
        text = format_status({'additionalVehicleStatus': {'maintenanceStatus': {
            'tyreStatusDriver': '265.125', 'tyreStatusPassenger': '266.375',
            'tyreStatusDriverRear': '267.625', 'tyreStatusPassengerRear': '265.125'}}})
        self.assertIn('左前 265.125 kPa、右前 266.375 kPa、左后 267.625 kPa、右后 265.125 kPa', text)
