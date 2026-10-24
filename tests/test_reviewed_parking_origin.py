import json
import sqlite3
import unittest
from tests import test_commute_tags as fixtures
from zeekr_control.reviewed_parking_origin import reviewed_parking_origin
from zeekr_control.parking_origin import parking_origin


class ReviewedParkingOriginTests(unittest.TestCase):
    setUp=fixtures.CommuteTagTests.setUp
    trip=fixtures.CommuteTagTests.trip

    def seed(self):
        self.trip('previous',self.start,(31.2,121.4),(31.21,121.41),trusted=False)
        self.previous_end=self.start+1200000;self.park=self.previous_end+600000;self.current=self.previous_end+18000000
        self.trip('current',self.current,(31.21,121.41),(31.2,121.4),trusted=False)
        self.location=dict(valid=True,plottable=True,trusted=False,coordinate_system='WGS84（社区解释）',latitude=31.21,longitude=121.41)
        self.meta=dict(version=1,basis='reviewed_historical_parking',reviewed=True,event_id='current',start_time=self.current,previous_event_id='previous',previous_parking_time=self.park)
        self.event=dict(id='current',kind='trip_end',start_time=self.current,end_time=self.current+1200000,partial=True)
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE report_observations(vehicle TEXT,state_time INTEGER,observed_at INTEGER,normalized_payload TEXT,decoder_version TEXT)')
            for identity in ['previous','current']:
                raw=json.loads(db.execute('SELECT summary FROM monitor_events WHERE id=?',(identity,)).fetchone()[0]);raw['partial']=True
                raw['report_v2']=dict(parking=self.state(self.park)) if identity=='previous' else dict(start=self.state(self.current))
                if identity=='current':raw['reviewed_start_parking']=self.meta;self.raw=raw
                db.execute('UPDATE monitor_events SET summary=? WHERE id=?',(json.dumps(raw),identity))
            for t in [self.park,self.current]:db.execute('INSERT INTO report_observations VALUES(?,?,?,?,?)',('car',t,t+1000,json.dumps(self.state(t)),'fixture'))
            for t in [self.previous_end,self.park,self.park+600000,self.current]:
                db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',('car','review-'+str(t),t,t+1000,30,json.dumps(self.location)))

    @staticmethod
    def state(t):return dict(state_time=t,observed_at=t+1000,odometer=44874,off=True,speed=None)

    def infer(self):
        with sqlite3.connect(self.db) as db:return reviewed_parking_origin(db,'car',self.event,self.raw)

    def test_reviewed_fragment_uses_original_point_preserving_gap_and_raw_state(self):
        self.seed();before=self.db.read_bytes();result=self.infer()
        self.assertEqual(result['point'],(31.21,121.41));self.assertTrue(result['reviewed']);self.assertEqual(result['source'],'parking_inferred')
        self.assertEqual(result['sampling_gap_seconds'],16800)
        self.assertEqual(before,self.db.read_bytes())
        row=next(r for r in self.tags.query('owner','car','2026-09-28')['events'] if r['id']=='current')
        self.assertTrue(row['partial']);self.assertIsNotNone(row['start_place']);self.assertEqual(row['start_place_evidence']['sampling_gap_seconds'],16800)
        self.assertIsNone(self.tags.commute._endpoint('car',self.current,self.current+1200000,True))

    def test_missing_review_wrong_scope_and_mismatched_mileage_are_rejected(self):
        self.seed()
        for change in [dict(reviewed=False),dict(version=2),dict(event_id='other'),dict(start_time=self.current+1),dict(previous_event_id='missing'),dict(previous_parking_time=self.current+1)]:
            with self.subTest(change=change):self.raw['reviewed_start_parking']=dict(self.meta,**change);self.assertIsNone(self.infer())
        self.raw['reviewed_start_parking']=self.meta
        self.raw['report_v2']['start']['odometer']=44875;self.assertIsNone(self.infer())
        self.raw['report_v2']['start']['odometer']=44874
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE monitor_events SET vehicle='other' WHERE id='previous'")
        self.assertIsNone(self.infer())

    def test_motion_or_stale_state_blocks_review(self):
        self.seed();t=self.park
        for patch in [dict(odometer=44875),dict(off=False),dict(speed=1),dict(odometer=True),dict(observed_at=t+60001)]:
            with self.subTest(patch=patch):
                data=dict(self.state(t),**patch)
                with sqlite3.connect(self.db) as db:db.execute('UPDATE report_observations SET normalized_payload=? WHERE state_time=?',(json.dumps(data),t))
                self.assertIsNone(self.infer())

    def test_coordinate_conflict_stale_location_or_intervening_trip_is_rejected(self):
        self.seed();t=self.park+600000
        with sqlite3.connect(self.db) as db:db.execute('UPDATE observations SET location=? WHERE state_time=?',(json.dumps(dict(self.location,latitude=32)),t))
        self.assertIsNone(self.infer())
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE observations SET location=?,observed_time=? WHERE state_time=?',(json.dumps(self.location),t+60001,t))
        self.assertIsNone(self.infer())
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE observations SET observed_time=state_time+1000 WHERE state_time=?',(t,))
            db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',('other-trip','car','trip_start','{}',self.current-100000))
        self.assertIsNone(self.infer())

    def test_late_movement_invalidates_reviewed_origin(self):
        self.seed()
        for kind, start, end in [('trip_start',self.current-60000,self.current-60000),
                                 ('trip_end',self.previous_end+60000,self.current-60000),
                                 ('trip_end',self.previous_end-60000,self.current+60000)]:
            with self.subTest(kind=kind,start=start,end=end):
                with sqlite3.connect(self.db) as db:
                    db.execute('INSERT OR REPLACE INTO monitor_events VALUES(?,?,?,?,?)',
                               ('late','car',kind,json.dumps(dict(start_time=start,end_time=end)),self.current+90000))
                self.assertIsNone(self.infer())

    def test_old_completed_trip_written_during_parking_does_not_invalidate_origin(self):
        self.seed()
        expected = self.infer()
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',
                       ('old','car','trip_end',json.dumps(dict(start_time=self.previous_end-120000,
                        end_time=self.previous_end-60000)),self.park+60000))
        self.assertEqual(self.infer(), expected)

    def test_recycled_review_source_is_unavailable_until_restored(self):
        self.seed()
        expected = self.infer()
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE trip_record_trash(vehicle TEXT,event_id TEXT)')
            db.execute("INSERT INTO trip_record_trash VALUES('car','previous')")
        self.assertIsNone(self.infer())
        with sqlite3.connect(self.db) as db:
            db.execute('DELETE FROM trip_record_trash')
        self.assertEqual(self.infer(), expected)

    def test_automatic_partial_inference_stays_disabled_and_limits_are_enforced(self):
        self.seed()
        with sqlite3.connect(self.db) as db:
            raw=dict(self.raw);raw.pop('reviewed_start_parking');db.execute("UPDATE monitor_events SET summary=? WHERE id='current'",(json.dumps(raw),))
            self.assertIsNone(parking_origin(db,'car',self.event))
            db.execute('DROP TABLE report_observations')
        self.assertIsNone(self.infer())

if __name__=='__main__':unittest.main()
