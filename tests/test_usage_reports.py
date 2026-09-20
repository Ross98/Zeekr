import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from zeekr_control.archive_reader import ArchiveReader
from zeekr_control.snapshot_archive import SnapshotArchive
from zeekr_control.tracks import day_bounds
from zeekr_control.usage_reports import UsageReports, period_window
from zeekr_control.usage_events import UsageEvents


class UsageReportsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=self.root/'tracks.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE monitor_events (id TEXT PRIMARY KEY,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
        self.db.chmod(0o600)
        self.archive=ArchiveReader(self.root/'snapshot-archive')
        self.reports=UsageReports(self.db,self.archive)
        self.day,_=day_bounds('2026-09-15')
        self.now,_=day_bounds('2026-10-05')

    def add(self, identity='trip', kind='trip_end', vehicle='car', day=None, **changes):
        stamp=self.day if day is None else day_bounds(day)[0]
        summary={'start_time':stamp+8*3600000,'end_time':stamp+9*3600000,
                 'duration_seconds':3600,'distance_km':40,'start_soc':70,'end_soc':60,
                 'soc_delta':-10,'partial':False,'battery_capacity_kwh':86,
                 'address':'PRIVATE-ADDRESS','vin':'PRIVATE-VIN','coordinates':[111600000,435600000]}
        summary.update(changes)
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO monitor_events VALUES (?,?,?,?,?)',
                       (identity,vehicle,kind,json.dumps(summary),1))
        return summary

    def report(self, period='month', date='2026-09-20', now=None):
        return self.reports.query('owner','car',period,date,self.now if now is None else now)

    def test_calendar_week_month_leap_year_and_previous_bounds(self):
        week=period_window('week','2026-09-20')
        self.assertEqual((week['start_date'],week['end_date']),('2026-09-14','2026-09-20'))
        self.assertEqual(week['previous_date'],'2026-09-07')
        month=period_window('month','2024-02-20')
        self.assertEqual(month['end_date'],'2024-02-29')
        self.assertEqual(month['days'],29)
        january=period_window('month','2026-01-01')
        self.assertEqual(january['previous_date'],'2025-12-01')
        for period,date in [('year','2026-09-20'),('week','2026-9-20'),('month','2026-02-30')]:
            with self.assertRaises(ValueError):period_window(period,date)

    def test_complete_and_partial_metrics_share_valid_sample_totals(self):
        self.add()
        self.add('partial',partial=True,distance_km=7)
        self.add('charge','charge_end',distance_km=0,start_soc=40,end_soc=80,soc_delta=40)
        self.add('charge-partial','charge_end',partial=True,start_soc=70,end_soc=75,soc_delta=5)
        data=self.report()['current']
        self.assertEqual(data['totals']['trip_count'],2)
        self.assertEqual(data['totals']['complete_trip_count'],1)
        self.assertEqual(data['totals']['distance_km'],47)
        self.assertEqual(data['totals']['complete_distance_km'],40)
        self.assertEqual(data['samples']['distance'],2)
        self.assertEqual(data['totals']['duration_seconds'],7200)
        self.assertEqual(data['totals']['partial_distance_km'],7)
        self.assertAlmostEqual(data['totals']['trip_estimated_kwh'],17.2)
        self.assertAlmostEqual(data['totals']['estimated_kwh_per_100km'],21.5)
        self.assertAlmostEqual(data['totals']['charge_estimated_kwh'],38.7)
        self.assertEqual(data['samples']['trip_energy'],2)
        self.assertEqual(data['samples']['charge_energy'],2)
        self.assertEqual(data['departure_hours'][8],2)

    def test_date_belongs_to_end_time_and_other_vehicles_are_excluded(self):
        self.add(day='2026-08-31',end_time=self.day,duration_seconds=3600)
        self.add('other',vehicle='other-car',distance_km=900)
        self.add('old',day='2026-08-15',distance_km=12)
        data=self.report()
        self.assertEqual(len(data['current']['events']),1)
        self.assertEqual(data['previous']['totals']['distance_km'],12)
        self.assertEqual(data['current']['events'][0]['duration_seconds'],None)

    def test_unknown_capacity_missing_soc_or_mixed_charge_never_estimates(self):
        for i,changes in enumerate([{'battery_capacity_kwh':None},{'start_soc':None},{'soc_delta':None},
                                   {'soc_delta':-9},{'end_soc':71,'soc_delta':1},{'report_v2':{'metrics':{'charge_overlap':True}}}]):
            self.add(str(i),**changes)
        data=self.report()['current']
        self.assertIsNone(data['totals']['trip_estimated_kwh'])
        self.assertIsNone(data['totals']['estimated_kwh_per_100km'])
        self.assertEqual(data['samples']['trip_energy'],0)

    def test_invalid_scalars_and_incomplete_flags_never_leak_or_count_as_complete(self):
        self.add('bad',distance_km={'secret':'PRIVATE-OBJECT'},start_soc=True,partial='false')
        self.add('nan',distance_km=float('nan'),battery_capacity_kwh=float('inf'))
        data=self.report()
        self.assertIsNone(data['current']['totals']['distance_km'])
        self.assertIsNone(data['current']['totals']['partial_distance_km'])
        encoded=json.dumps(data,allow_nan=False)
        for private in ('PRIVATE-', 'latitude','longitude','coordinates','111600000'):
            self.assertNotIn(private,encoded)

    def test_current_period_keeps_counts_but_suppresses_whole_period_trend(self):
        self.add()
        self.add('old',day='2026-08-15',distance_km=20)
        data=self.report(now=self.day+10*3600000)
        self.assertEqual(data['current']['totals']['distance_km'],40)
        self.assertEqual(data['current']['status'],'ongoing')
        self.assertFalse(data['comparison']['comparable'])
        self.assertIsNone(data['comparison']['metrics']['distance_km']['percent'])

    def test_closed_period_trend_and_zero_base_are_explicit(self):
        self.add();self.add('old',day='2026-08-15',distance_km=20)
        data=self.report()
        self.assertTrue(data['comparison']['comparable'])
        self.assertEqual(data['comparison']['metrics']['distance_km']['percent'],100)
        self.assertIsNone(data['comparison']['metrics']['charge_count']['percent'])
        self.assertEqual(data['comparison']['metrics']['charge_count']['reason'],'zero_base')

    def test_missing_data_is_not_reported_as_zero_distance(self):
        data=self.report()['current']
        self.assertEqual(data['totals']['trip_count'],0)
        self.assertIsNone(data['totals']['distance_km'])
        self.assertEqual(data['coverage']['days_with_reads'],0)
        self.assertTrue(all(row['coverage']=='missing' for row in data['days']))

    def test_coverage_uses_metadata_only_and_current_account(self):
        writer=SnapshotArchive(self.archive.root)
        raw=json.dumps({'updateTime':self.day,'vin':'PRIVATE-VIN'})
        for offset in (0,60000):
            writer.append('owner','car',raw,self.day,self.day+offset,self.day+offset,'monitor')
        writer.append('different','car',raw,self.day,self.day+86400000,self.day+86400000,'monitor')
        # Corrupting payload must not affect metadata-only coverage.
        with sqlite3.connect(self.archive.root/'2026'/'09.sqlite3') as db:
            db.execute("UPDATE payloads SET compressed_json=X'00'")
        data=self.report()['current']
        self.assertEqual(data['coverage']['reads'],2)
        self.assertEqual(data['coverage']['new_states'],1)
        self.assertEqual(data['coverage']['days_with_reads'],1)
        self.assertEqual(data['days'][14]['coverage'],'observed')

    def test_future_events_and_future_days_are_distinct(self):
        self.add(day='2026-09-25')
        data=self.report(now=self.day)['current']
        self.assertEqual(data['totals']['trip_count'],0)
        self.assertEqual(data['days'][24]['coverage'],'future')
        upcoming=self.report(date='2026-11-01',now=self.day)
        self.assertEqual(upcoming['current']['status'],'upcoming')

    def test_repeat_at_period_start_is_not_a_new_vehicle_update(self):
        lower,_=day_bounds('2026-09-01')
        writer=SnapshotArchive(self.archive.root)
        raw=json.dumps({'updateTime':lower-60000})
        writer.append('owner','car',raw,lower-60000,lower-60000,lower-60000,'monitor')
        writer.append('owner','car',raw,lower-60000,lower,lower,'monitor')
        coverage=self.report()['current']['coverage']
        self.assertEqual(coverage['reads'],1)
        self.assertEqual(coverage['repeats'],1)
        self.assertEqual(coverage['new_states'],0)

    def test_efficiency_uses_only_its_own_eligible_distance_samples(self):
        self.add()
        self.add('unknown-energy',distance_km=200,battery_capacity_kwh=None)
        self.add('tiny',distance_km=2,start_soc=70,end_soc=69,soc_delta=-1)
        result=self.report()['current']
        self.assertEqual(result['totals']['distance_km'],242)
        self.assertAlmostEqual(result['totals']['estimated_kwh_per_100km'],21.5)
        self.assertEqual(result['samples']['efficiency'],1)

    def test_empty_database_read_does_not_create_storage(self):
        absent=self.root/'absent.sqlite3'
        result=UsageReports(absent,self.archive).query('owner','car','week','2026-09-20',self.now)
        self.assertEqual(result['current']['events'],[])
        self.assertFalse(absent.exists())

    def test_malformed_records_have_explicit_scan_quality(self):
        with sqlite3.connect(self.db) as db:
            for i,encoded in enumerate(('[]','{','{"end_time":null}')):
                db.execute('INSERT INTO monitor_events VALUES (?,?,?,?,?)',(str(i),'car','trip_end',encoded,1))
        result=self.report()
        self.assertEqual(result['history_quality']['unreadable_or_undated'],3)

    def test_single_event_lookup_is_bounded_safe_and_vehicle_scoped(self):
        self.add()
        store=UsageEvents(self.db)
        self.assertEqual(store.get('car','trip')['distance_km'],40)
        for car,key in [('other','trip'),('car','../session.json')]:
            with self.assertRaises(ValueError):store.get(car,key)


if __name__=='__main__':unittest.main()
