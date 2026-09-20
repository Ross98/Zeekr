import json
import unittest

import test_usage_reports as report_fixtures
from zeekr_control.snapshot_archive import SnapshotArchive
from zeekr_control.tracks import day_bounds


class UsageCalendarTests(unittest.TestCase):
    add=report_fixtures.UsageReportsTests.add

    def setUp(self):
        report_fixtures.UsageReportsTests.setUp(self)
        from zeekr_control.usage_calendar import UsageCalendar
        self.calendar=UsageCalendar(self.db,self.archive,clock=lambda:self.now)

    def query(self,date='2026-09-20',**kwargs):
        return self.calendar.query('owner','car',date,**kwargs)

    def observation(self,minute=0,stamp=None,observed=None,scope='owner',vehicle='car',**changes):
        stamp=self.day+minute*60000 if stamp is None else stamp
        raw={'updateTime':stamp,'vin':'PRIVATE-VIN','position':{'latitude':111600000},
             'basicVehicleStatus':{'engineStatus':'engine_off','speed':0,'speedValidity':True},
             'additionalVehicleStatus':{'electricVehicleStatus':{'ptReady':0,'chargeSts':0,
                                       'chargerState':0,'statusOfChargerConnection':0}}}
        raw.update(changes)
        observed=stamp if observed is None else observed
        SnapshotArchive(self.archive.root).append(scope,vehicle,json.dumps(raw),stamp,observed,observed,'monitor')

    def test_month_grid_leap_year_and_weekday(self):
        result=self.query('2024-02-01')
        self.assertEqual(len(result['days']),29)
        self.assertEqual(result['weekday_offset'],3)
        self.assertEqual(result['window']['previous_date'],'2024-01-01')
        with self.assertRaises(ValueError):self.query('2026-02-30')

    def test_cross_midnight_events_on_both_days_without_splitting_distance(self):
        boundary=day_bounds('2026-09-16')[0]
        self.add(start_time=boundary-1800000,end_time=boundary+1800000)
        result=self.query()
        self.assertEqual([d['trip_count'] for d in result['days'][14:16]],[1,1])
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['events'][0]['distance_km'],40)
        self.assertTrue(result['events'][0]['cross_midnight'])

    def test_overlap_includes_events_ending_next_month_and_excludes_midnight_endpoint(self):
        boundary=day_bounds('2026-10-01')[0]
        self.add(start_time=boundary-1800000,end_time=boundary+1800000)
        self.add('ends-at-midnight',start_time=boundary-3600000,end_time=boundary)
        september=self.query();october=self.query('2026-10-01')
        self.assertEqual(september['days'][-1]['trip_count'],2)
        self.assertEqual(october['days'][0]['trip_count'],1)
        self.assertEqual(len(september['events']),2)

    def test_unknown_or_reversed_start_only_marks_end_day(self):
        for identity,start in [('unknown',None),('reversed',self.day+2*86400000)]:
            self.add(identity,start_time=start)
        result=self.query()
        self.assertEqual(result['days'][14]['trip_count'],2)
        self.assertEqual(sum(d['trip_count'] for d in result['days']),2)
        self.assertTrue(all(e['partial'] for e in result['events']))

    def test_future_days_and_events_never_look_like_missing_or_observed(self):
        self.add(day='2026-09-25');self.observation(stamp=day_bounds('2026-09-25')[0])
        result=self.query(now=self.day)
        self.assertEqual(result['days'][24]['coverage'],'future')
        self.assertEqual(result['events'],[])
        self.assertEqual(result['days'][0]['coverage'],'missing')
        self.assertTrue(all(d['coverage']=='future' for d in self.query('2026-11-01',now=self.day)['days']))

    def test_parking_is_observed_sample_evidence_not_all_day_or_repeated_counts(self):
        self.observation()
        self.observation(observed=self.day+60000)
        self.observation(minute=5)
        row=self.query()['days'][14]
        self.assertEqual(row['reads'],3)
        self.assertEqual(row['effective_states'],2)
        self.assertEqual(row['parked_samples'],2)
        self.assertEqual((row['parking_first'],row['parking_last']),(self.day,self.day+300000))
        self.assertNotIn('parking_duration',row)

    def test_revision_replaces_parked_evidence_and_stale_only_is_limited(self):
        self.observation()
        self.observation(observed=self.day+60000,basicVehicleStatus={'engineStatus':'engine_on','speed':20,'speedValidity':True})
        row=self.query()['days'][14]
        self.assertEqual(row['parked_samples'],0)
        self.assertEqual(row['effective_states'],1)
        self.observation(stamp=self.day,observed=self.day+86400000)
        stale=self.query()['days'][15]
        self.assertEqual(stale['coverage'],'limited')
        self.assertEqual(stale['parked_samples'],0)

    def test_conflicting_speed_or_unknown_charge_never_means_parked(self):
        self.observation(basicVehicleStatus={'engineStatus':'engine_off','speed':20,'speedValidity':True})
        self.observation(minute=5,additionalVehicleStatus={'electricVehicleStatus':{'ptReady':0,'chargeSts':99}})
        self.assertEqual(self.query()['days'][14]['parked_samples'],0)

    def test_account_vehicle_scope_and_projection(self):
        self.add();self.add('foreign',vehicle='different')
        self.observation();self.observation(minute=5,scope='different');self.observation(minute=10,vehicle='different')
        result=self.query()
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['days'][14]['reads'],1)
        encoded=json.dumps(result)
        for secret in ('PRIVATE-','111600000','position','latitude','vin'):
            self.assertNotIn(secret,encoded)

    def test_empty_calendar_does_not_create_storage(self):
        from zeekr_control.usage_calendar import UsageCalendar
        from zeekr_control.archive_reader import ArchiveReader
        root=self.root/'absent'
        result=UsageCalendar(root/'events.sqlite3',ArchiveReader(root/'archive')).query('owner','car','2026-09-20',now=self.now)
        self.assertEqual(result['events'],[])
        self.assertFalse(root.exists())


if __name__=='__main__':unittest.main()
