import json
import unittest

import test_archive_reader as fixtures
from zeekr_control.parameter_dictionary import FIELDS

SOC = 'additionalVehicleStatus.electricVehicleStatus.chargeLevel'
TEMP = 'additionalVehicleStatus.climateStatus.interiorTemp'


class VehicleResearchTests(unittest.TestCase):
    append = fixtures.ArchiveReaderTests.append

    def setUp(self):
        fixtures.ArchiveReaderTests.setUp(self)
        from zeekr_control.vehicle_research import VehicleResearch
        self.api = VehicleResearch(self.reader, clock=lambda: self.start + 86400000)

    def query(self, path=''):
        return self.api.query('owner', 'car', '2026-09-20', '2026-09-20', path)

    def field(self, result, path=SOC):
        return next(row for row in result['fields'] if row['path'] == path)

    def test_empty_covers_public_catalog_without_creating_storage(self):
        result = self.query()
        self.assertEqual(len(result['fields']), sum(not f['private'] for f in FIELDS.values()))
        self.assertEqual(result['counts']['returned_fields'], 0)
        self.assertEqual(result['counts']['samples'], 0)
        self.assertEqual(len(result['scenes']), 5)
        self.assertFalse(self.root.exists())

    def test_read_counts_and_revision_canonicalization(self):
        self.append(); self.append(60000, state_offset=0)
        self.append(120000, soc=69, state_offset=0)
        self.append(180000, soc=60)
        result = self.query(SOC)
        row = self.field(result)
        self.assertEqual(result['counts']['reads'], 4)
        self.assertEqual(result['quality'], dict(new=2, repeat=1, revision=1, invalid=0))
        self.assertEqual(row['read_counts']['known'], 4)
        self.assertEqual(row['samples'], 2)
        self.assertEqual(row['numeric']['mean'], 64.5)
        self.assertEqual([p['number'] for p in result['detail']['points']], [69, 60])
        self.assertEqual(row['changes'], 1)

    def test_bad_time_regression_revisit_not_counted_as_new(self):
        self.append(); self.append(120000)
        self.append(180000, state_offset=60000)
        self.append(240000, state_offset=120000)
        self.append(1800000, state_offset=0)
        self.append(1860000, extra={'updateTime': None})
        self.assertEqual(self.query()['counts']['samples'], 2)

    def test_numeric_invalid_empty_missing_and_zero_separate(self):
        self.append(soc=0); self.append(60000, soc=None)
        self.append(120000, soc=200)
        self.append(180000, extra={'additionalVehicleStatus': {}})
        row = self.field(self.query())
        self.assertEqual(row['read_counts'], dict(known=1, pending=0, empty=1, invalid=1, missing=1))
        self.assertEqual(row['numeric']['min'], 0)
        self.assertEqual(row['numeric']['count'], 1)

    def test_field_time_missing_and_stale_are_not_usable_temperatures(self):
        self.append()
        self.append(60000, extra={'additionalVehicleStatus': {'climateStatus': {
            'interiorTemp': 20, 'temperatureUpdateTime': self.start-3600000}}})
        row = self.field(self.query(TEMP), TEMP)
        self.assertEqual(row['samples'], 0)
        self.assertEqual(row['time_excluded'], 2)

    def test_gap_preserved_and_transition_has_uncertain_bounds(self):
        self.append(); self.append(60000, soc=69); self.append(1800000, soc=68)
        detail = self.query(SOC)['detail']
        self.assertTrue(detail['points'][-1]['gap_before'])
        self.assertEqual(detail['transitions'][0]['from_time'], self.start)
        self.assertEqual(detail['transitions'][0]['to_time'], self.start+60000)
        self.assertTrue(detail['transitions'][-1]['gap'])

    def test_foreign_and_unknown_data_not_projected(self):
        self.append(extra={'PRIVATE-UNKNOWN-PATH': {'secret': 'PRIVATE-UNKNOWN'}})
        self.append(60000, soc=99, scope='other')
        self.append(120000, soc=98, vehicle='other')
        result = self.query()
        self.assertEqual(result['counts']['reads'], 1)
        self.assertGreater(result['counts']['unmapped_paths'], 0)
        for secret in ('PRIVATE', 'latitude', 'longitude', 'scope_key', 'digest', 'accessToken'):
            self.assertNotIn(secret, json.dumps(result))
        for path in ('vin', 'position.latitude', 'no.such.path'):
            with self.assertRaises(ValueError): self.query(path)

    def test_bounded_dates(self):
        for a,b in [('bad','2026-09-20'),('2026-09-20','2026-09-19'),('2026-08-01','2026-09-20')]:
            with self.assertRaises(ValueError): self.api.query('owner','car',a,b)

    def test_sampling_retains_extremes_and_first_last_without_connecting(self):
        from zeekr_control.vehicle_research import sample_points
        points = [dict(time=i, number=999 if i == 401 else -999 if i == 407 else i % 10) for i in range(3000)]
        sampled = sample_points(points)
        self.assertLessEqual(len(sampled), 600)
        self.assertEqual(sampled[0], points[0]); self.assertEqual(sampled[-1], points[-1])
        self.assertIn(points[401], sampled); self.assertIn(points[407], sampled)

    def test_four_wheel_spread_requires_all_four_same_snapshot(self):
        def wheels(values):
            return {'additionalVehicleStatus': {'maintenanceStatus': dict(zip(
                ['tyreStatus'+side for side in ('Driver','Passenger','DriverRear','PassengerRear')], values))}}
        self.append(extra=wheels([240,241,239,242]))
        self.append(60000, extra=wheels([240,245,239]))
        scene = next(s for s in self.query()['scenes'] if s['id']=='tyres')
        self.assertEqual(scene['wheel_spread']['count'],1)
        self.assertEqual(scene['wheel_spread']['max'],3)

    def test_cabin_separate_clock_deduplication_and_scenario(self):
        def cabin(stamp):
            return {'basicVehicleStatus':{'engineStatus':'engine_running','speedValidity':True,'speed':30},
                    'additionalVehicleStatus':{'climateStatus':{'interiorTemp':20,'exteriorTemp':28,'temperatureUpdateTime':stamp}}}
        self.append(extra=cabin(self.start));self.append(60000,extra=cabin(self.start))
        result=self.query(TEMP)
        row=self.field(result,TEMP)
        self.assertEqual(row['samples'],1)
        self.assertEqual(row['scenarios']['driving']['samples'],1)
        self.assertEqual(result['scenes'][0]['paired_delta']['mean'],-8)

    def test_pending_numeric_keeps_raw_mean_separate_from_meaning(self):
        path='additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.voltage'
        for offset,value in [(0,12),(60000,13)]:
            self.append(offset,extra={'additionalVehicleStatus':{'maintenanceStatus':{'mainBatteryStatus':{'voltage':value}}}})
        row=self.field(self.query(path),path)
        self.assertEqual(row['pending_samples'],2)
        self.assertEqual(row['numeric']['mean'],12.5)
        self.assertIn('待核实',row['reason'])

    def test_raw_types_and_overflow_distribution_preserve_denominator(self):
        path='additionalVehicleStatus.electricVehicleStatus.chargerState'
        for index,value in enumerate([True,1,'1']+list(range(2,28))):
            self.append(index*60000,extra={'additionalVehicleStatus':{'electricVehicleStatus':{'chargerState':value}}})
        row=self.field(self.query(path),path)
        self.assertEqual(row['distinct'],29)
        self.assertEqual(sum(d['count'] for d in row['distribution'])+row['distribution_other'],row['samples'])

    def test_configuration_is_current_background_not_fabricated_history(self):
        path='vehicleMetadata.updateTime'
        result=self.api.query('owner','car','2026-09-20','2026-09-20',path,
            current={'fields':[dict(path=path,raw='10',status='pending',value='含义待核实')]})
        row=self.field(result,path)
        self.assertEqual(row['disposition'],'configuration')
        self.assertEqual(row['samples'],0)
        self.assertEqual(row['current']['raw'],'10')

    def test_event_conditions_keep_partial_and_missing_temperature(self):
        from zeekr_control.usage_events import project
        from unittest.mock import Mock
        event=project('test','trip_end',dict(start_time=self.start,end_time=self.start+3600000,
            duration_seconds=3600,distance_km=40,start_soc=70,end_soc=60,soc_delta=-10,
            battery_capacity_kwh=86,partial=False))
        self.api.events=Mock()
        self.api.events.between.return_value={'events':[event,dict(event,id='partial',partial=True)]}
        result=self.query()['event_conditions']
        self.assertEqual(result['total'],2)
        temp=next(g for g in result['groups'] if g['dimension']=='temperature')
        self.assertEqual(temp['label'],'温度缺样')
        self.assertEqual(temp['consumption']['count'],1)
        self.assertEqual(temp['consumption']['mean'],21.5)

    def test_rate_and_cadence_exclude_gaps(self):
        self.append(soc=70);self.append(60000,soc=69);self.append(1800000,soc=60)
        row=self.field(self.query(SOC))
        self.assertEqual(row['cadence_seconds']['count'],1)
        self.assertEqual(row['cadence_seconds']['mean'],60)
        self.assertEqual(row['rate_per_minute']['mean'],-1)

    def test_cabin_matches_outside_band_and_raw_climate_code(self):
        for index,code in enumerate([0,1]):
            self.append(index*60000,extra={'additionalVehicleStatus':{'climateStatus':{
                'temperatureUpdateTime':self.start+index*60000,'interiorTemp':28-index,
                'exteriorTemp':30,'cdsClimateActive':code}}})
        groups=self.query()['scenes'][0]['conditions']
        rows=[r for r in groups if r['path'].endswith('.cdsClimateActive')]
        self.assertEqual(len(rows),2)
        self.assertEqual({r['raw'] for r in rows},{'0','1'})
        self.assertEqual({r['outside_band'] for r in rows},{'车外高于 25°C'})

    def test_boolean_is_not_a_physical_numeric_reading(self):
        self.append(soc=True)
        row=self.field(self.query())
        self.assertEqual(row['read_counts']['invalid'],1)
        self.assertEqual(row['samples'],0)

    def test_long_raw_changes_survive_truncated_display(self):
        path='temStatus.swVersion'
        self.append(extra={'temStatus':{'swVersion':'x'*121+'a'}})
        self.append(60000,extra={'temStatus':{'swVersion':'x'*121+'b'}})
        result=self.query(path)
        self.assertEqual(result['detail']['field']['changes'],1)
        self.assertTrue(result['detail']['transitions'][0]['display_limited'])

    def test_boundary_repeat_and_revision_do_not_claim_new_vehicle_samples(self):
        self.append(-60000)
        self.append(0,state_offset=-60000)
        self.append(60000,state_offset=-60000,soc=69)
        result=self.query()
        self.assertEqual(result['quality'],dict(new=0,repeat=1,revision=1,invalid=0))
        self.assertEqual(result['counts']['samples'],0)


if __name__ == '__main__': unittest.main()
