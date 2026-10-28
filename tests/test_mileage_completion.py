"""Manual completion preserves raw evidence and commits exactly one trip."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from test_monitor import BASE, sample
from zeekr_control.monitor import Monitor
from zeekr_control.mileage_gaps import MileageGaps
from zeekr_control.usage_events import UsageEvents
from zeekr_control.errors import RecordConflict


class MileageCompletionTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.tracks=Path(folder.name)/'private'/'tracks.sqlite3'
        self.monitor=Monitor(self.tracks)
        self.monitor.observe('car',sample(0,km=100,soc=50),BASE)
        self.monitor.observe('car',sample(10800,km=126,soc=44),BASE+10800000)
        self.gaps=MileageGaps(self.tracks.parent/'mileage-gaps.sqlite3',self.tracks)
        self.gap=self.gaps.between('car',BASE,BASE+20000000,BASE+20000000)[0]

    def payload(self,**extra):
        def stamp(ms):return datetime.fromtimestamp(ms/1000,ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%dT%H:%M')
        return dict(gap_id=self.gap['id'],revision=0,start=stamp(BASE+3600000),end=stamp(BASE+7200000),
                    start_place='合成住所',end_place='合成公司',**extra)

    def complete(self,data=None,owner='owner',vehicle='car',guard=None):
        return self.gaps.update(owner,vehicle,data or self.payload(),guard=guard,now=BASE+20000000)

    def test_complete_counts_once_and_never_changes_raw_evidence_or_sends(self):
        with sqlite3.connect(self.gaps.path) as db:raw_before=db.execute('SELECT * FROM mileage_gaps').fetchall()
        result=self.complete()
        with sqlite3.connect(self.gaps.path) as db:self.assertEqual(db.execute('SELECT * FROM mileage_gaps').fetchall(),raw_before)
        self.assertEqual(self.gaps.between('car',BASE,BASE+20000000,BASE+20000000),[])
        history=self.gaps.history('owner','car',BASE,BASE+20000000,BASE+20000000)
        self.assertEqual(history[0]['status'],'completed')
        self.assertEqual(history[0]['odometer_before'],100)
        self.assertEqual(history[0]['soc_after'],44)
        self.assertEqual(history[0]['completion']['start_place'],'合成住所')
        events=UsageEvents(self.tracks).between('car',BASE,BASE+20000000)['events']
        self.assertEqual(len(events),1);self.assertEqual(events[0]['distance_km'],26)
        self.assertEqual(events[0]['record_source'],'manual_completion')
        self.assertIsNone(events[0]['estimated_kwh'])
        self.assertIsNone(events[0]['soc_delta'])
        with self.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT delivery FROM monitor_events WHERE id=?',(result['event_id'],)).fetchone()[0],'cancelled')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM monitor_event_alerts').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM monitor_event_media').fetchone()[0],0)
        with self.assertRaises(RecordConflict):self.complete()
        self.assertEqual(len(UsageEvents(self.tracks).between('car',BASE,BASE+20000000)['events']),1)

    def test_edit_updates_the_same_trip_and_labels_are_owner_scoped(self):
        first=self.complete()
        data=self.payload();data.update(revision=1,end_place='修改后公司')
        edited=self.complete(data)
        self.assertEqual(first['event_id'],edited['event_id'])
        self.assertEqual(edited['revision'],2)
        with sqlite3.connect(self.gaps.path) as db:
            versions=db.execute('SELECT revision,body FROM gap_completion_history ORDER BY revision').fetchall()
        self.assertEqual([r[0] for r in versions],[1,2])
        self.assertEqual(json.loads(versions[0][1])['end_place'],'合成公司')
        self.assertEqual(json.loads(versions[1][1])['end_place'],'修改后公司')
        self.assertIsNone(self.gaps.completion('other','car',edited['event_id']))
        self.assertEqual(self.gaps.completion('owner','car',edited['event_id'])['end_place'],'修改后公司')
        with self.assertRaises(ValueError):self.complete(data,owner='other')
        self.assertEqual(len(UsageEvents(self.tracks).between('car',BASE,BASE+20000000)['events']),1)

    def test_invalid_times_names_vehicle_and_mileage_are_rejected(self):
        cases=[dict(end='2020-01-01T00:00'),dict(start='2030-01-01T00:00'),
               dict(start='2024-01-01T08:00',end='2024-01-01T08:00'),
               dict(start_place=' '),dict(end_place='bad\nplace'),dict(distance_km=27)]
        for change in cases:
            data=self.payload();data.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.complete(data)
        with self.assertRaises(ValueError):self.complete(vehicle='other')
        self.assertEqual(self.monitor.events(),[])

    def test_guard_failure_rolls_back_both_databases(self):
        calls=[]
        def guard():
            calls.append(1)
            if len(calls)>1:raise RecordConflict('synthetic account switch')
        with self.assertRaises(RecordConflict):self.complete(guard=guard)
        self.assertEqual(len(self.gaps.between('car',BASE,BASE+20000000,BASE+20000000)),1)
        self.assertEqual(self.monitor.events(),[])

    def test_concurrent_confirmation_can_create_only_one_trip(self):
        def confirm(_):
            try:return self.complete()['event_id']
            except RecordConflict:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(confirm,range(2)))
        self.assertEqual(sum(v is not None for v in results),1)
        self.assertEqual(len(self.monitor.events()),1)

    def test_overlap_with_existing_trip_rejects_completion(self):
        summary=dict(start_time=BASE+3600000,end_time=BASE+7200000,duration_seconds=3600,distance_km=10,partial=False)
        with self.monitor.tracks.connect() as db:
            db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES('existing','car','trip_end',?,'',?)",(json.dumps(summary),BASE+7200000))
        with self.assertRaisesRegex(RecordConflict,'重叠'):self.complete()
        self.assertEqual(len(self.gaps.between('car',BASE,BASE+20000000,BASE+20000000)),1)
        self.assertEqual(len(self.monitor.events()),1)

    def test_incomplete_manual_marker_does_not_break_event_projection(self):
        from zeekr_control.usage_events import project
        event=project('ordinary','trip_end',dict(start_time=BASE,end_time=BASE+60000,
            duration_seconds=60,manual_completion=dict(source='mileage_gap')))
        self.assertNotIn('record_source',event)

    def test_corrected_date_moves_mileage_instead_of_duplicating_it(self):
        from zeekr_control.tracks import day_bounds
        boundary=day_bounds('2024-01-02')[0]
        left,right=boundary-86400000,boundary+10800000
        self.gaps.record('cross',dict(time=left,km=100,off=True,charging=False,soc=50),
                         dict(time=right,observed=right,km=126,off=True,charging=False,soc=44))
        gap=self.gaps.between('cross',left,right+1,right)[0]
        data=self.payload();data.update(gap_id=gap['id'],start='2024-01-01T22:00',end='2024-01-01T23:00')
        first=self.gaps.update('owner','cross',data,now=right)
        data.update(revision=1,start='2024-01-01T23:00',end='2024-01-02T01:00')
        second=self.gaps.update('owner','cross',data,now=right)
        self.assertEqual(first['event_id'],second['event_id'])
        self.assertEqual(second['date'],'2024-01-02')
        self.assertEqual(UsageEvents(self.tracks).between('cross',left,boundary)['events'],[])
        events=UsageEvents(self.tracks).between('cross',boundary,right+1)['events']
        self.assertEqual([e['distance_km'] for e in events],[26])
        self.assertEqual(self.gaps.between('cross',left,right+1,right),[])

    def test_confirmed_soc_calculates_energy_without_changing_mileage_or_raw_evidence(self):
        data=self.payload();data.update(energy_basis='confirmed_soc',start_soc=50,end_soc=44)
        result=self.gaps.update('owner','car',data,profile={'battery_capacity_kwh':86},now=BASE+20000000)
        event=UsageEvents(self.tracks).get('car',result['event_id'])
        self.assertEqual(event['estimated_kwh'],5.16)
        self.assertEqual(event['energy_source'],'manual_soc_capacity_estimate')
        self.assertTrue(event['partial'])
        self.assertEqual(event['distance_km'],26)
        self.assertEqual(self.gaps.history('owner','car',BASE,BASE+20000000,BASE+20000000)[0]['soc_after'],44)
        data.update(revision=1,end_soc=45)
        edited=self.gaps.update('owner','car',data,profile={'battery_capacity_kwh':86},now=BASE+20000000)
        self.assertEqual(edited['event_id'],result['event_id'])
        self.assertEqual(UsageEvents(self.tracks).get('car',result['event_id'])['estimated_kwh'],4.3)
        self.assertEqual(len(self.monitor.events()),1)
        data.update(revision=2,energy_basis='none')
        self.gaps.update('owner','car',data,profile={'battery_capacity_kwh':86},now=BASE+20000000)
        self.assertIsNone(UsageEvents(self.tracks).get('car',result['event_id'])['estimated_kwh'])
        self.assertEqual(len(self.monitor.events()),1)

    def test_preview_is_read_only_and_validates_soc_and_server_capacity(self):
        data=self.payload();data.update(operation='preview',energy_basis='confirmed_soc',start_soc=50,end_soc=44)
        result=self.gaps.update('owner','car',data,profile={'battery_capacity_kwh':86},now=BASE+20000000)
        self.assertEqual(result['event']['estimated_kwh'],5.16)
        self.assertEqual(self.monitor.events(),[])
        self.assertEqual(self.gaps.history('owner','car',BASE,BASE+20000000,BASE+20000000)[0]['status'],'pending')
        for change in ({'start_soc':True},{'end_soc':101},{'end_soc':60},{'energy_basis':'fake'},{'battery_capacity_kwh':100}):
            bad=dict(data,**change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.gaps.update('owner','car',bad,profile={'battery_capacity_kwh':86},now=BASE+20000000)
        with self.assertRaisesRegex(ValueError,'电池容量'):
            self.gaps.update('owner','car',data,profile={},now=BASE+20000000)

    def test_preview_and_saved_trip_share_existing_weighted_bill_cost(self):
        from zeekr_control.personal_store import PersonalStore
        from zeekr_control.charge_ledger import ChargeLedger
        from zeekr_control.usage_calendar import UsageCalendar
        from zeekr_control.archive_reader import ArchiveReader
        store=PersonalStore(self.tracks.parent/'personal.sqlite3')
        summary=dict(start_time=BASE+600000,end_time=BASE+1200000,duration_seconds=600,
                     start_soc=20,end_soc=50,soc_delta=30,battery_capacity_kwh=86,partial=False)
        with self.monitor.tracks.connect() as db:
            db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES('charge','car','charge_end',?,'',?)",(json.dumps(summary),BASE+1200000))
        ledger=ChargeLedger(store,self.tracks)
        ledger.update('owner','car',dict(action='save',revision=0,event_id='charge',date='2024-01-01',source='public',amount='30',metered_kwh='30'))
        calendar=UsageCalendar(self.tracks,ArchiveReader(self.tracks.parent/'archive'),clock=lambda:BASE+20000000,store=store)
        data=self.payload();data.update(operation='preview',energy_basis='confirmed_soc',start_soc=50,end_soc=44)
        proposal=self.gaps.update('owner','car',data,profile={'battery_capacity_kwh':86},now=BASE+20000000)
        preview=self.gaps.preview_cost(calendar,'scope','owner','car',proposal)
        self.assertAlmostEqual(preview['energy_kwh'],5.16)
        self.assertAlmostEqual(preview['kwh_per_100km'],19.846154)
        self.assertEqual(preview['energy_cost']['status'],'partial')
        self.assertAlmostEqual(preview['energy_cost']['estimated_cents'],360)
        foreign=self.gaps.preview_cost(calendar,'scope','other','car',proposal)
        self.assertIsNone(foreign['energy_cost']['estimated_cents'])
        data['operation']='save'
        result=self.gaps.update('owner','car',data,profile={'battery_capacity_kwh':86},now=BASE+20000000)
        saved=calendar.query('scope','car','2024-01-01',owner='owner')
        trip=next(e for e in saved['events'] if e['id']==result['event_id'])
        self.assertEqual(trip['energy_cost'],preview['energy_cost'])
        self.assertEqual(saved['totals']['actual_cents'],3000)
        from zeekr_control.usage_reports import aggregate,period_window
        totals=aggregate([trip],period_window('month','2024-01-01'),BASE+20000000)['totals']
        self.assertAlmostEqual(totals['trip_estimated_kwh'],5.16)
        self.assertAlmostEqual(totals['estimated_kwh_per_100km'],19.846154)
