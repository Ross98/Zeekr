import json
import unittest

import test_usage_reports as report_fixtures
from zeekr_control.snapshot_archive import SnapshotArchive
from zeekr_control.tracks import day_bounds


class UsageCalendarTests(unittest.TestCase):
    def test_daily_metrics_and_month_totals_use_event_end_day_without_double_counting(self):
        boundary=day_bounds('2026-09-16')[0]
        self.add(start_time=boundary-1800000,end_time=boundary+1800000,duration_seconds=3600)
        self.add('unknown-distance',distance_km=None)
        result=self.query()
        self.assertIsNone(result['days'][14]['distance_km'])
        self.assertEqual(result['days'][15]['distance_km'],40)
        self.assertEqual(result['totals']['distance_km'],40)
        self.assertEqual(result['totals']['distance_samples'],1)
        self.assertEqual(result['totals']['trip_count'],2)

    def test_duration_end_day_totals_preserve_missing_zero_and_partial_samples(self):
        boundary=day_bounds('2026-09-16')[0]
        self.add('cross',start_time=boundary-1800000,end_time=boundary+1800000,duration_seconds=3600)
        self.add('partial',partial=True,duration_seconds=3600)
        self.add('missing',duration_seconds=None)
        self.add('zero',start_time=self.day,end_time=self.day,duration_seconds=0)
        self.add('charge',kind='charge_end')
        self.add('next-month',day='2026-10-01')
        result=self.query()
        day=result['days'][14]
        self.assertEqual(day['duration_seconds'],3600)
        self.assertEqual(day['duration_samples'],2)
        self.assertEqual(day['partial_duration_samples'],2)
        self.assertEqual(day['ended_trip_count'],3)
        self.assertEqual(result['days'][15]['duration_seconds'],3600)
        self.assertIsNone(result['days'][13]['duration_seconds'])
        self.assertEqual(result['totals']['duration_seconds'],7200)
        self.assertEqual(result['totals']['duration_samples'],3)
        self.assertEqual(result['totals']['partial_duration_samples'],2)
        self.assertEqual(result['totals']['trip_count'],4)

    def test_actual_bill_dates_zero_missing_amount_and_scoped_pending(self):
        from zeekr_control.personal_store import PersonalStore
        from zeekr_control.charge_ledger import ChargeLedger
        from zeekr_control.usage_calendar import UsageCalendar
        store=PersonalStore(self.root/'personal.sqlite3');ledger=ChargeLedger(store,self.db)
        self.add('charge-a',kind='charge_end',start_soc=40,end_soc=80,soc_delta=40)
        self.add('charge-b',kind='charge_end',start_soc=40,end_soc=80,soc_delta=40)
        ledger.update('owner','car',dict(action='save',revision=0,event_id='charge-a',date='2026-09-17',source='unknown',amount='0'))
        ledger.update('owner','car',dict(action='save',revision=1,event_id='charge-b',date='2026-09-15',source='public'))
        self.calendar=UsageCalendar(self.db,self.archive,clock=lambda:self.now,store=store)
        result=self.query()
        self.assertEqual(result['totals']['actual_cents'],0)
        self.assertEqual(result['totals']['pending_count'],1)
        self.assertIsNone(result['days'][14]['actual_cents'])
        self.assertEqual(result['days'][16]['actual_cents'],0)
        events={e['id']:e for e in result['events']}
        self.assertFalse(events['charge-a']['needs_bill']);self.assertTrue(events['charge-b']['needs_bill'])
        self.assertEqual(events['charge-b']['bill']['source'],'public')
        foreign=self.calendar.query('other','car','2026-09-01',owner='other')
        self.assertIsNone(foreign['totals']['actual_cents']);self.assertEqual(foreign['totals']['pending_count'],2)

    def test_next_month_end_does_not_inflate_month_distance(self):
        boundary=day_bounds('2026-10-01')[0]
        self.add(start_time=boundary-1800000,end_time=boundary+1800000)
        result=self.query()
        self.assertIsNone(result['totals']['distance_km'])
        self.assertEqual(result['totals']['trip_count'],0)

    def test_cost_basis_uses_prior_month_bill_without_changing_daily_payments(self):
        from zeekr_control.personal_store import PersonalStore
        from zeekr_control.charge_ledger import ChargeLedger
        from zeekr_control.usage_calendar import UsageCalendar
        store=PersonalStore(self.root/'personal.sqlite3')
        self.add('charge',kind='charge_end',day='2026-08-31',start_soc=0,end_soc=20,soc_delta=20)
        self.add('trip',day='2026-09-15',start_soc=20,end_soc=10,soc_delta=-10)
        ChargeLedger(store,self.db).update('owner','car',dict(action='save',revision=0,event_id='charge',date='2026-08-31',source='home',amount='25',metered_kwh='20',parking_fee='9'))
        self.calendar=UsageCalendar(self.db,self.archive,clock=lambda:self.now,store=store)
        result=self.query()
        self.assertEqual(result['days'][14]['energy_cost']['estimated_cents'],1250)
        self.assertEqual(result['totals']['energy_cost']['known_kwh'],8.6)
        self.assertIsNone(result['totals']['actual_cents'])
        self.assertEqual(result['totals']['energy_cost']['parking_samples'],0)
        foreign=self.calendar.query('other','car','2026-09-01',owner='other')
        self.assertIsNone(foreign['totals']['energy_cost']['estimated_cents'])
        self.assertNotIn('PRIVATE',json.dumps(result))

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
