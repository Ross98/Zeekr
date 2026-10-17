import json
import sqlite3
import unittest

from tests import test_commute_tags as fixtures
from zeekr_control.parking_destination import parking_destination
from zeekr_control.reviewed_parking_destination import reviewed_parking_destination


class ReviewedParkingDestinationTests(unittest.TestCase):
    setUp=fixtures.CommuteTagTests.setUp
    trip=fixtures.CommuteTagTests.trip

    def seed(self):
        self.trip('partial',self.start,(31.2,121.4),(31.21,121.41),trusted=False)
        self.end=self.start+1200000;self.next_start=self.end+1800000
        self.before=self.end-195000;self.after=self.next_start+75000
        self.trip('next',self.next_start,(31.21,121.41),(31.2,121.4),trusted=False)
        self.point=dict(valid=True,plottable=True,trusted=False,coordinate_system='WGS84（社区解释）',latitude=31.21,longitude=121.41)
        self.meta=dict(version=1,basis='reviewed_historical_parking',reviewed=True,event_id='partial',end_time=self.end,
                       previous_trusted_time=self.before,next_trusted_time=self.after,next_event_id='next')
        with sqlite3.connect(self.db) as db:
            raw=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='partial'").fetchone()[0])
            raw['partial']=True;raw.pop('end_location',None);raw['reviewed_end_parking']=self.meta
            self.raw=raw;db.execute("UPDATE monitor_events SET summary=? WHERE id='partial'",(json.dumps(raw),))
            for t in [self.before,self.end,self.end+60000,self.end+600000,self.next_start,self.after]:
                loc=dict(self.point,trusted=t in (self.before,self.after))
                db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',('car','review-'+str(t),t,t+1000,30,json.dumps(loc)))
        self.event=dict(id='partial',kind='trip_end',start_time=self.start,end_time=self.end,partial=True)

    def infer(self):
        with sqlite3.connect(self.db) as db:return reviewed_parking_destination(db,'car',self.event,self.raw)

    def test_reviewed_partial_preserves_fragment_and_exposes_real_gap_readonly(self):
        self.seed();before=self.db.read_bytes();result=self.infer()
        self.assertEqual(result['point'],(31.21,121.41))
        self.assertEqual(result['source'],'parking_inferred');self.assertTrue(result['reviewed'])
        self.assertEqual(result['sampling_gap_seconds'],1200)
        self.assertEqual(self.db.read_bytes(),before)
        row=next(r for r in self.tags.query('owner','car','2026-09-28')['events'] if r['id']=='partial')
        self.assertTrue(row['partial']);self.assertIsNotNone(row['end_place'])
        self.assertEqual(row['end_place_evidence']['sampling_gap_seconds'],1200)
        self.assertIsNone(self.tags.commute._endpoint('car',self.start,self.end,False))

    def test_unreviewed_partial_and_wrong_identity_or_times_are_rejected(self):
        self.seed()
        for patch in [dict(reviewed=False),dict(version=2),dict(event_id='other'),dict(end_time=self.end+1),
                      dict(basis='automatic'),dict(next_event_id='missing'),dict(previous_trusted_time=self.end-900001),
                      dict(next_trusted_time=self.next_start+180001)]:
            with self.subTest(patch=patch):
                self.raw['reviewed_end_parking']=dict(self.meta,**patch);self.assertIsNone(self.infer())
        self.raw.pop('reviewed_end_parking');self.assertIsNone(self.infer())
        with sqlite3.connect(self.db) as db:self.assertIsNone(reviewed_parking_destination(db,'other',self.event,self.raw))

    def test_conflicting_stale_or_untrusted_context_blocks_review(self):
        self.seed()
        for t,loc,delay in [(self.before,dict(self.point,trusted=False),1000),
                            (self.after,dict(self.point,trusted=True,latitude=31.22),1000),
                            (self.end+60000,dict(self.point,latitude=31.22),1000),
                            (self.end,self.point,60001)]:
            with self.subTest(t=t,loc=loc,delay=delay):
                with sqlite3.connect(self.db) as db:
                    old=db.execute('SELECT location,observed_time FROM observations WHERE cache_key=?',('review-'+str(t),)).fetchone()
                    db.execute('UPDATE observations SET location=?,observed_time=? WHERE cache_key=?',(json.dumps(loc),t+delay,'review-'+str(t)))
                self.assertIsNone(self.infer())
                with sqlite3.connect(self.db) as db:db.execute('UPDATE observations SET location=?,observed_time=? WHERE cache_key=?',(*old,'review-'+str(t)))

    def test_intervening_trip_and_next_vehicle_mismatch_are_rejected(self):
        self.seed()
        with sqlite3.connect(self.db) as db:db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',('intervening','car','trip_start','{}',self.end+700000))
        self.assertIsNone(self.infer())
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM monitor_events WHERE id='intervening'")
            db.execute("UPDATE monitor_events SET vehicle='other' WHERE id='next'")
        self.assertIsNone(self.infer())

    def test_strict_automatic_path_does_not_accept_unreviewed_fragment(self):
        self.seed()
        with sqlite3.connect(self.db) as db:
            raw=dict(self.raw);raw.pop('reviewed_end_parking');db.execute("UPDATE monitor_events SET summary=? WHERE id='partial'",(json.dumps(raw),))
            self.assertIsNone(parking_destination(db,'car',self.event))


if __name__=='__main__':unittest.main()
