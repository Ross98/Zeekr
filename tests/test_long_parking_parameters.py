"""Long parking evidence preserves raw readings without treating caches as measurements."""
import unittest

import test_archive_reader as fixtures
from test_parameter_studies import point
from zeekr_control.parameter_studies import evidence_profiles, study_for
from zeekr_control.vehicle_parameters import parameters
from zeekr_control.web_model import build_model
from zeekr_control.vehicle_research import VehicleResearch


PREFIX = 'additionalVehicleStatus.'
VOLTAGE = PREFIX + 'maintenanceStatus.mainBatteryStatus.voltage'
TEMP = PREFIX + 'climateStatus.interiorTemp'


def snapshot(voltage=5, engine='engine_off', dcdc=0):
    return {'updateTime': 1791885495000,
            'basicVehicleStatus': {'engineStatus': engine},
            'additionalVehicleStatus': {
                'maintenanceStatus': {'mainBatteryStatus': {'voltage': voltage}},
                'electricVehicleStatus': {'dcDcActvd': dcdc},
                'climateStatus': {'interiorTemp': 26.3, 'exteriorTemp': 24.2,
                                  'temperatureUpdateTime': 1791511046497}}}


class LongParkingProjectionTests(unittest.TestCase):
    def field(self, raw, path):
        return next(f for f in parameters(raw, build_model(raw))['fields'] if f['path'] == path)

    def test_old_temperature_shows_warning_and_retains_raw_and_source_time(self):
        row = self.field(snapshot(), TEMP)
        self.assertIn('旧温度', row['value'])
        self.assertEqual(row['raw'], '26.3')
        self.assertEqual(row['updated_time'], 1791511046497)
        self.assertEqual(row['value_validity'], 'stale')

    def test_fresh_temperature_and_missing_clock_do_not_claim_staleness(self):
        raw = snapshot()
        raw['additionalVehicleStatus']['climateStatus']['temperatureUpdateTime'] = raw['updateTime']
        self.assertNotIn('旧温度', self.field(raw, TEMP)['value'])
        del raw['additionalVehicleStatus']['climateStatus']['temperatureUpdateTime']
        self.assertNotIn('旧温度', self.field(raw, TEMP)['value'])

    def test_suspected_sleep_voltage_retains_raw_without_claiming_battery_failure(self):
        row = self.field(snapshot(), VOLTAGE)
        self.assertEqual(row['value_validity'], 'suspect')
        self.assertEqual(row['status'], 'pending')
        self.assertEqual(row['raw'], '5')
        self.assertIn('疑似', row['value'])

    def test_other_voltages_and_missing_or_active_state_not_rejected(self):
        for voltage, engine, dcdc in [(5, 'engine_running', 0), (5, 'engine_off', 1),
                                      (5, None, 0), (5, 'engine_off', None),
                                      (6, 'engine_off', 0), (12.8, 'engine_off', 0)]:
            with self.subTest(voltage=voltage, engine=engine, dcdc=dcdc):
                self.assertNotEqual(self.field(snapshot(voltage, engine, dcdc), VOLTAGE)
                                    .get('value_validity'), 'suspect')


class LongParkingResearchTests(unittest.TestCase):
    append = fixtures.ArchiveReaderTests.append

    def setUp(self):
        fixtures.ArchiveReaderTests.setUp(self)
        self.api = VehicleResearch(self.reader, clock=lambda: self.start + 86400000)

    def test_sleep_voltage_excluded_from_numeric_stats_but_raw_distribution_kept(self):
        for offset, voltage in [(0, 13.2), (60000, 5)]:
            raw = snapshot(voltage)
            raw['updateTime'] = self.start + offset
            self.append(offset, extra=raw)
        result = self.api.query('owner', 'car', '2026-09-20', '2026-09-20', VOLTAGE)
        row = result['detail']['field']
        self.assertEqual(row['samples'], 2)
        self.assertEqual(row['numeric']['count'], 1)
        self.assertEqual(row['numeric']['mean'], 13.2)
        self.assertEqual(sum(d['count'] for d in row['distribution']), 2)
        self.assertIsNone(result['detail']['points'][-1]['number'])
        self.assertIn('疑似占位值', row['reason'])


class LongParkingStudyTests(unittest.TestCase):
    def test_multi_day_constant_parking_evidence_does_not_confirm_trigger(self):
        path = 'parkTime.status'
        samples = [point(i, **{path: 1790140000000}) for i in (0, 1440, 5760)]
        evidence = evidence_profiles(samples)
        self.assertEqual(evidence[path]['parked_constant_span_seconds'], 345600)
        row = {'path': path, 'status': 'single_value', 'name': '停车时间', 'pending': True}
        self.assertNotEqual(study_for(row, evidence)['stage'], 'cross_checked')

    def test_service_days_frozen_across_parked_days_are_recorded(self):
        path = PREFIX + 'maintenanceStatus.daysToService'
        evidence = evidence_profiles([point(i, **{path: 310}) for i in (0, 1440, 5760)])
        self.assertEqual(evidence['daysToService']['parked_constant_days'], 4)
        row = {'path': path, 'status': 'single_value', 'name': '保养天数', 'pending': True}
        self.assertIn('停车', study_for(row, evidence)['definition'])
        self.assertNotEqual(study_for(row, evidence)['stage'], 'cross_checked')

    def test_dcdc_on_while_parked_is_counterexample_to_driving(self):
        path = PREFIX + 'electricVehicleStatus.dcDcActvd'
        evidence = evidence_profiles([point(0, **{path: 1}), point(1, **{path: 0})])
        self.assertEqual(evidence['dcDcActvd']['parked_active_samples'], 1)
        self.assertEqual(evidence['dcDcActvd']['parked_inactive_samples'], 1)

    def test_driving_or_changed_values_break_constant_parking_evidence(self):
        path = 'parkTime.status'
        for middle in [point(1440, trip=True, **{path: 1790140000000}),
                       point(1440, **{path: 1790140060000})]:
            samples = [point(0, **{path: 1790140000000}), middle,
                       point(5760, **{path: 1790140000000})]
            self.assertEqual(evidence_profiles(samples)[path]['parked_constant_span_seconds'], 0)

    def test_temperature_and_voltage_evidence_identifies_cache_candidates_only(self):
        clock = PREFIX + 'climateStatus.temperatureUpdateTime'
        dcdc = PREFIX + 'electricVehicleStatus.dcDcActvd'
        values = {clock: 1790140000000, VOLTAGE: 5, dcdc: 0,
                  'basicVehicleStatus.engineStatus': 'engine_off'}
        evidence = evidence_profiles([point(1440, **values), point(1441, trip=True, **values)])
        self.assertEqual(evidence['temperatureUpdateTime']['stale_samples'], 2)
        self.assertEqual(evidence['aux_voltage']['suspected_sleep_samples'], 1)
