"""All saved-parking consumers share identity, interpretation and evidence."""
import json
import sqlite3
import unittest
from tests import test_parking_places as fixtures
from zeekr_control.daily_timeline import DailyTimeline
from zeekr_control.parking_analytics import ParkingAnalytics
from zeekr_control.usage_calendar import UsageCalendar


class ParkingUnificationTests(unittest.TestCase):
    def setUp(self):
        fixtures.ParkingPlaceTests.setUp(self)
        fixtures.ParkingPlaceTests.save_name(self,radius_m=150)
        self.raw['position'].update(latitude=108001800,posCanBeTrusted=False)
        self.raw['additionalVehicleStatus']['drivingBehaviourStatus']={'gearAutoStatus':0}
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE observations(id INTEGER PRIMARY KEY,vehicle TEXT,state_time INTEGER,observed_time INTEGER,location TEXT)')
            for minute,lat,trusted in [(4,30,True),(5,30.0005,False),(6,30.0005,False)]:
                stamp=self.lower+minute*60000
                point=dict(valid=True,plottable=True,trusted=trusted,latitude=lat,longitude=120,coordinate_system='WGS84（社区解释）')
                db.execute('INSERT INTO observations(vehicle,state_time,observed_time,location) VALUES(?,?,?,?)',('car',stamp,stamp+2000,json.dumps(point)))
        self.timeline=DailyTimeline(self.database,self.archive,self.store)
    def results(self):
        analytics=ParkingAnalytics(self.archive,self.database,store=self.store,owner='owner').query('scope','car','2026-09-20','2026-09-20')['events'][0]
        day=self.timeline.query('scope','car','2026-09-20',owner='owner')
        row=next(r for r in day['records'] if r['type']=='parking' and r['start_time']==self.lower+300000)
        month=self.timeline.calendar.query('scope','car','2026-09-20',owner='owner')
        return analytics,row,month
    def test_daily_calendar_analytics_and_year_share_reference_and_record_id(self):
        analytics,row,month=self.results()
        self.assertEqual(analytics['place_confidence'],'reference')
        self.assertEqual(analytics['place_label'],row['end_place']['label'])
        self.assertEqual(row['end_place_evidence']['source'],'parking_reference')
        place=next(p for p in month['totals']['parking_places'] if p['record_id']==row['id'])
        self.assertEqual(place['label'],'自家车库')
        self.assertEqual(place['confidence'],'reference')
        year=self.timeline.year('scope','car','2026',owner='owner')
        self.assertTrue(any(p['key']==place['key'] and p['confidence']=='reference' for p in year['frequent_parking_places']))
        self.assertNotIn('position',row)
        self.assertFalse(any(k.startswith('_') for k in analytics))
    def test_single_record_assignment_and_undo_propagate_to_all_consumers(self):
        _,row,_=self.results()
        data=dict(date='2026-09-20',record_id=row['id'],side='end',action='assign',name='仅本次校正',revision=0)
        preview=self.timeline.update('owner','car',dict(data,operation='preview'),scope='scope')
        self.timeline.update('owner','car',dict(data,operation='save',preview_token=preview['preview_token']),scope='scope')
        analytics,row,month=self.results()
        self.assertEqual(analytics['place_label'],'仅本次校正')
        self.assertEqual(row['end_place']['label'],'仅本次校正')
        self.assertEqual(next(p for p in month['totals']['parking_places'] if p['record_id']==row['id'])['label'],'仅本次校正')
        self.timeline.update('owner','car',dict(operation='undo',revision=1),scope='scope')
        self.assertEqual(self.results()[0]['place_label'],'自家车库')

    def test_observed_parking_uses_same_name_without_reference_evidence(self):
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE observations SET location=json_set(location,'$.trusted',json('true'))")
        analytics,row,month=self.results()
        place=next(p for p in month['totals']['parking_places'] if p['record_id']==row['id'])
        self.assertEqual(analytics['place_confidence'], 'observed')
        self.assertEqual(place['confidence'], 'observed')
        self.assertEqual(analytics['place_label'],row['end_place']['label'])
        self.assertIsNone(place['evidence'])
        self.assertNotIn('end_place_evidence',row)

    def test_missing_corroboration_stays_unknown_in_all_consumers(self):
        with sqlite3.connect(self.database) as db:
            db.execute('DELETE FROM observations WHERE state_time=?',(self.lower+240000,))
        analytics,row,month=self.results()
        self.assertEqual(analytics['place_confidence'],'unknown')
        self.assertEqual(row['end_place']['label'],'位置未知')
        self.assertFalse(any(p['record_id']==row['id'] for p in month['totals']['parking_places']))
        year=self.timeline.year('scope','car','2026',owner='owner')
        self.assertFalse(any(p['record_id']==row['id'] for p in year['frequent_parking_places']))
    def test_legacy_fragment_correction_reaches_calendar_and_year(self):
        from zeekr_control.daily_timeline import digest
        _,row,_=self.results()
        fragments=ParkingAnalytics(self.archive).query('scope','car','2026-09-20','2026-09-20')['sessions']
        old_id='parking_'+digest(fragments[0]['id'])[:32]
        body=dict(record_id=old_id,side='end',action='assign',name='旧片段校正',candidate='自家车库',
                  key=row['end_place']['key'],target_key=None,latitude=30.0005,longitude=120,remember=False)
        self.store.change('owner','car','place_corrections','save','old-correction',body,0)
        analytics,row,month=self.results()
        self.assertEqual(analytics['place_label'],'旧片段校正')
        self.assertEqual(row['end_place']['label'],'旧片段校正')
        self.assertTrue(any(p['label']=='旧片段校正' for p in month['totals']['parking_places']))
        self.assertTrue(any(p['label']=='旧片段校正' for p in self.timeline.year('scope','car','2026',owner='owner')['frequent_parking_places']))

    def test_calendar_observation_source_is_read_once_and_keeps_coverage(self):
        original=self.archive.iter_records;calls=[]
        def count(*args,**kwargs):
            calls.append(1);yield from original(*args,**kwargs)
        self.archive.iter_records=count
        month=UsageCalendar(self.database,self.archive,store=self.store).query('scope','car','2026-09-20',owner='owner')
        self.assertEqual(len(calls),1)
        day=next(d for d in month['days'] if d['date']=='2026-09-20')
        self.assertEqual(day['reads'],4)
        self.assertEqual(day['effective_states'],4)
    def test_owner_scope_and_movement_do_not_receive_reference(self):
        other=self.timeline.query('scope','car','2026-09-20',owner='other')
        self.assertTrue(all(r['end_place']['label']!='自家车库' for r in other['records'] if r['type']=='parking'))
        self.raw['basicVehicleStatus']['speed']=2
        self.assertTrue(all(e['place_confidence']!='reference' for e in ParkingAnalytics(self.archive,self.database,store=self.store,owner='owner').query('scope','car','2026-09-20','2026-09-20')['events']))
