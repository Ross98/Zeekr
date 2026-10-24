import json
import sqlite3
import unittest

from tests import test_commute_tags as fixtures
from zeekr_control.parking_destination import parking_destination


class ParkingDestinationTests(unittest.TestCase):
    setUp=fixtures.CommuteTagTests.setUp
    trip=fixtures.CommuteTagTests.trip

    def seed(self):
        self.trip('current',self.start,(31.2,121.4),(31.21,121.41))
        self.end=self.start+1200000
        self.park=self.end+90000
        self.location=dict(valid=True,plottable=True,trusted=False,coordinate_system='WGS84（社区解释）',latitude=31.21,longitude=121.41)
        self.event=dict(id='current',kind='trip_end',start_time=self.start,end_time=self.end,partial=False)
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE report_observations(vehicle TEXT,state_time INTEGER,observed_at INTEGER,normalized_payload TEXT,decoder_version TEXT)')
            raw=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='current'").fetchone()[0])
            raw['end_location']=self.location
            raw['report_v2']=dict(end=self.telemetry(self.end),parking=self.telemetry(self.park))
            db.execute("UPDATE monitor_events SET summary=? WHERE id='current'",(json.dumps(raw),))
            db.execute("UPDATE observations SET location=? WHERE cache_key='current-1'",(json.dumps(self.location),))
            for t in range(self.end,self.park+1,30000):
                payload=self.telemetry(t)
                db.execute('INSERT INTO report_observations VALUES(?,?,?,?,?)',('car',t,t+1000,json.dumps(payload),'fixture'))
                db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',('car','park-'+str(t),t,t+1000,30,json.dumps(self.location)))

    @staticmethod
    def telemetry(t):return dict(state_time=t,observed_at=t+1000,odometer=45000,off=True,speed=0)

    def infer(self,**changes):
        with sqlite3.connect(self.db) as db:return parking_destination(db,'car',dict(self.event,**changes))

    def change_summary(self,fn):
        with sqlite3.connect(self.db) as db:
            raw=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='current'").fetchone()[0]);fn(raw)
            db.execute("UPDATE monitor_events SET summary=? WHERE id='current'",(json.dumps(raw),))

    def test_stable_parked_samples_infer_destination_without_writes(self):
        self.seed();before=self.db.read_bytes();result=self.infer()
        self.assertEqual(result['point'],(31.21,121.41))
        self.assertEqual(result['sample_time'],self.park)
        self.assertEqual(result['source'],'parking_inferred')
        self.assertEqual(result['sampling_gap_seconds'],30)
        self.assertEqual(result['parking_seconds'],90)
        self.assertGreaterEqual(result['stationary_samples'],2)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertIsNone(self.infer(partial=True))
        with sqlite3.connect(self.db) as db:self.assertIsNone(parking_destination(db,'other',self.event))

    def test_gap_uses_largest_distinct_location_interval_not_telemetry_or_parking_duration(self):
        self.seed()
        with sqlite3.connect(self.db) as db:
            db.execute('DELETE FROM observations WHERE state_time=?',(self.end+30000,))
        self.assertEqual(self.infer()['sampling_gap_seconds'],60)
        self.assertEqual(self.infer()['parking_seconds'],90)

    def test_invalid_summary_or_moving_parking_is_rejected(self):
        self.seed()
        with sqlite3.connect(self.db) as db:original=db.execute("SELECT summary FROM monitor_events WHERE id='current'").fetchone()[0]
        changes=[lambda r:r['report_v2']['parking'].update(off=False),
                 lambda r:r['report_v2']['parking'].update(odometer=45001),
                 lambda r:r['report_v2']['end'].update(odometer=True),
                 lambda r:r['report_v2']['parking'].update(speed=1),
                 lambda r:r['report_v2']['parking'].update(state_time=self.end+900001),
                 lambda r:r['report_v2']['parking'].update(state_time=self.end+59000),
                 lambda r:r['report_v2']['end'].update(state_time=self.end+1),
                 lambda r:r['end_location'].update(coordinate_system='GCJ-02（社区解释）'),
                 lambda r:r['end_location'].update(latitude=float('nan')),
                 lambda r:r.update(partial=True),lambda r:r.update(report_v2={})]
        for change in changes:
            with self.subTest(change=change):
                with sqlite3.connect(self.db) as db:db.execute("UPDATE monitor_events SET summary=? WHERE id='current'",(original,))
                self.change_summary(change);self.assertIsNone(self.infer())

    def test_any_intermediate_motion_invalid_or_stale_sample_blocks_inference(self):
        self.seed();t=self.end+30000
        for values in [dict(off=False),dict(speed=1),dict(speed=-1),dict(odometer=45001),dict(observed_at=t+60001),dict(state_time=t-1)]:
            with self.subTest(values=values):
                payload=dict(self.telemetry(t),**values)
                with sqlite3.connect(self.db) as db:db.execute('UPDATE report_observations SET normalized_payload=? WHERE state_time=?',(json.dumps(payload),t))
                self.assertIsNone(self.infer())
        with sqlite3.connect(self.db) as db:db.execute('UPDATE report_observations SET normalized_payload=? WHERE state_time=?',('invalid-json',t))
        self.assertIsNone(self.infer())

    def test_coordinate_drift_missing_or_stale_parking_fix_blocks_inference(self):
        self.seed();t=self.end+30000
        for location in [dict(self.location,latitude=31.22),dict(self.location,plottable=False),dict(self.location,latitude=True)]:
            with self.subTest(location=location):
                with sqlite3.connect(self.db) as db:db.execute('UPDATE observations SET location=? WHERE state_time=?',(json.dumps(location),t))
                self.assertIsNone(self.infer())
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE observations SET location=? WHERE state_time=?',(json.dumps(self.location),t))
            db.execute('UPDATE observations SET observed_time=state_time+60001 WHERE state_time=?',(self.park,))
        self.assertIsNone(self.infer())

    def test_missing_tables_boundaries_and_intervening_trip_are_rejected(self):
        self.seed()
        with sqlite3.connect(self.db) as db:db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',('next','car','trip_start','{}',self.end+60000))
        self.assertIsNone(self.infer())
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM monitor_events WHERE id='next'")
            db.execute('DELETE FROM report_observations WHERE state_time=?',(self.park,))
        self.assertIsNone(self.infer())
        with sqlite3.connect(self.db) as db:db.execute('DROP TABLE report_observations')
        self.assertIsNone(self.infer())

    def test_delayed_movement_start_blocks_destination_inference(self):
        self.seed()
        stamp = self.end+30000
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',
                       ('late-start','car','trip_start',json.dumps({'start_time':stamp}),self.park+30000))
        self.assertIsNone(self.infer())

    def test_late_write_of_older_movement_does_not_block_destination(self):
        self.seed()
        expected = self.infer()
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',
                       ('old-start','car','trip_start',json.dumps({'start_time':self.end-60000}),self.end+30000))
        self.assertEqual(self.infer(), expected)

    def test_long_sampling_gap_and_truncated_stream_are_rejected(self):
        self.seed();later=self.end+600000
        self.change_summary(lambda r:r['report_v2'].update(parking=self.telemetry(later)))
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE report_observations SET state_time=?,observed_at=?,normalized_payload=? WHERE state_time=?',
                       (later,later+1000,json.dumps(self.telemetry(later)),self.park))
            db.execute('UPDATE observations SET state_time=?,observed_time=? WHERE state_time=?',(later,later+1000,self.park))
        self.assertIsNone(self.infer())
        self.change_summary(lambda r:r['report_v2'].update(parking=self.telemetry(self.park)))
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE report_observations SET state_time=?,observed_at=?,normalized_payload=? WHERE state_time=?',
                       (self.park,self.park+1000,json.dumps(self.telemetry(self.park)),later))
            db.execute('UPDATE observations SET state_time=?,observed_time=? WHERE state_time=?',(self.park,self.park+1000,later))
            for _ in range(257):
                db.execute('INSERT INTO report_observations VALUES(?,?,?,?,?)',('car',self.end,self.end+1000,json.dumps(self.telemetry(self.end)),'duplicate'))
        self.assertIsNone(self.infer())

    def test_query_marks_end_estimate_without_changing_commute_trust(self):
        self.seed();result=self.tags.query('owner','car','2026-09-28');row=result['events'][0]
        self.assertIsNotNone(row['end_place'])
        self.assertEqual(row['end_place_evidence']['source'],'parking_inferred')
        self.assertEqual(row['end_place_evidence']['sampling_gap_seconds'],30)
        self.assertIsNone(self.tags.commute._endpoint('car',self.start,self.end,False))

    def test_trusted_arrival_takes_priority(self):
        self.seed()
        with sqlite3.connect(self.db) as db:db.execute("UPDATE observations SET location=? WHERE cache_key='current-1'",(json.dumps(dict(self.location,trusted=True)),))
        row=self.tags.query('owner','car','2026-09-28')['events'][0]
        self.assertNotIn('end_place_evidence',row)


if __name__=='__main__':unittest.main()
