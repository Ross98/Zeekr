import json
import sqlite3
import unittest

from tests import test_commute_tags as fixtures
from zeekr_control.parking_origin import parking_origin


class ParkingOriginTests(unittest.TestCase):
    setUp = fixtures.CommuteTagTests.setUp
    trip = fixtures.CommuteTagTests.trip

    def seed(self):
        self.current = self.start + 8*86400000
        self.trip('previous', self.start, (31.2,121.4), (31.21,121.41))
        self.trip('current', self.current, (31.21,121.41), (31.2,121.4))
        self.location = dict(valid=True, plottable=True, trusted=False,
                             coordinate_system='WGS84（社区解释）', latitude=31.21, longitude=121.41)
        with sqlite3.connect(self.db) as db:
            for identity, odo in [('previous',45856),('current',45856)]:
                raw=json.loads(db.execute('SELECT summary FROM monitor_events WHERE id=?',(identity,)).fetchone()[0])
                if identity=='previous':
                    raw['end_location']=dict(self.location,trusted=True)
                    raw['report_v2']=dict(end=dict(state_time=raw['end_time'],odometer=odo,off=True,speed=0))
                else:
                    raw['start_location']=self.location
                    raw['report_v2']=dict(start=dict(state_time=raw['start_time'],odometer=odo))
                    db.execute("UPDATE observations SET location=? WHERE cache_key='current-0'",(json.dumps(self.location),))
                db.execute('UPDATE monitor_events SET summary=? WHERE id=?',(json.dumps(raw),identity))
            t=self.current-34000
            db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',
                       ('car','parked',t,t+2000,30,json.dumps(self.location)))
        return dict(id='current',start_time=self.current,end_time=self.current+1200000,partial=False)

    def infer(self,event=None):
        with sqlite3.connect(self.db) as db:
            return parking_origin(db,'car',event or self.event)

    def edit(self,identity,change):
        with sqlite3.connect(self.db) as db:
            raw=json.loads(db.execute('SELECT summary FROM monitor_events WHERE id=?',(identity,)).fetchone()[0])
            change(raw)
            db.execute('UPDATE monitor_events SET summary=? WHERE id=?',(json.dumps(raw),identity))

    def test_matching_parked_arrival_and_unchanged_odometer_infer_origin_readonly(self):
        self.event=self.seed();before=self.db.read_bytes()
        result=self.infer()
        self.assertEqual(result['point'],(31.21,121.41))
        self.assertEqual(result['source'],'parking_inferred')
        self.assertEqual(result['sample_time'],self.current-34000)
        self.assertEqual(result['previous_event_id'],'previous')
        self.assertEqual(result['sampling_gap_seconds'],34)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertIsNone(self.infer(dict(self.event,partial=True)))
        with sqlite3.connect(self.db) as db:self.assertIsNone(parking_origin(db,'foreign',self.event))

    def test_trusted_arrival_reference_is_accepted_but_stale_reference_is_rejected(self):
        self.event=self.seed()
        def reference(raw):
            raw['end_location_reference']=dict(age_seconds=240,location=raw['end_location'])
            raw['end_location']=self.location
        self.edit('previous',reference)
        self.assertIsNotNone(self.infer())
        self.edit('previous',lambda raw:raw['end_location_reference'].update(age_seconds=301))
        self.assertIsNone(self.infer())

    def test_movement_missing_corrupt_or_conflicting_evidence_stays_unknown(self):
        self.event=self.seed()
        with sqlite3.connect(self.db) as db:
            original={i:raw for i,raw in db.execute('SELECT id,summary FROM monitor_events')}
        changes=[('current',lambda r:r['report_v2']['start'].update(odometer=45857)),
                 ('current',lambda r:r['report_v2']['start'].update(odometer=True)),
                 ('current',lambda r:r['report_v2']['start'].update(state_time=self.current+1)),
                 ('previous',lambda r:r['report_v2']['end'].update(off=False)),
                 ('previous',lambda r:r['report_v2']['end'].update(speed=1)),
                 ('previous',lambda r:r.update(partial=True)),
                 ('previous',lambda r:r['end_location'].update(trusted=False)),
                 ('previous',lambda r:r['end_location'].update(latitude=32)),
                 ('current',lambda r:r['start_location'].update(latitude=32)),
                 ('current',lambda r:r.update(report_v2={})),
                 ('previous',lambda r:r.update(end_time=self.current+1))]
        for identity,change in changes:
            with self.subTest(identity=identity,change=change):
                with sqlite3.connect(self.db) as db:
                    for i,raw in original.items():db.execute('UPDATE monitor_events SET summary=? WHERE id=?',(raw,i))
                self.edit(identity,change)
                self.assertIsNone(self.infer())

    def test_old_predeparture_point_or_late_observation_stays_unknown(self):
        self.event=self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE observations SET state_time=? WHERE cache_key='parked'",(self.current-180001,))
        self.assertIsNone(self.infer())
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE observations SET state_time=?,observed_time=? WHERE cache_key='parked'",(self.current-34000,self.current+120000))
        self.assertIsNone(self.infer())

    def test_unfinished_intervening_trip_or_month_old_parking_is_rejected(self):
        self.event=self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',
                       ('intervening','car','trip_start','{}',self.current-86400000))
        self.assertIsNone(self.infer())
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM monitor_events WHERE id='intervening'")
        def make_old(raw):
            raw['end_time']=self.current-32*86400000
            raw['report_v2']['end']['state_time']=raw['end_time']
        self.edit('previous',make_old)
        self.assertIsNone(self.infer())

    def test_invalid_latest_predeparture_sample_is_not_skipped(self):
        self.event=self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',
                       ('car','newest',self.current-1000,self.current-500,30,'invalid-json'))
        self.assertIsNone(self.infer())

    def test_query_marks_estimate_and_leaves_commute_trust_unchanged(self):
        self.event=self.seed()
        result=self.tags.query('owner','car','2026-10-06')
        row=next(r for r in result['events'] if r['id']=='current')
        self.assertIsNotNone(row['start_place'])
        self.assertEqual(row['start_place_evidence']['source'],'parking_inferred')
        self.assertEqual(row['start_place_evidence']['sampling_gap_seconds'],34)
        self.assertIsNone(self.tags.commute._endpoint('car',self.current,self.current+1200000,True))

    def test_trusted_trip_origin_takes_priority(self):
        self.event=self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE observations SET location=? WHERE cache_key='current-0'",(json.dumps(dict(self.location,trusted=True)),))
        result=self.tags.query('owner','car','2026-10-06')
        row=next(r for r in result['events'] if r['id']=='current')
        self.assertNotIn('start_place_evidence',row)


if __name__=='__main__':unittest.main()
