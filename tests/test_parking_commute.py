"""Automatic commute matching retains corroborated parking provenance."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from tests import test_commute_tags as commute_fixtures
from tests import test_parking_origin as origin_fixtures
from tests import test_parking_destination as destination_fixtures


class ParkingCommuteTests(unittest.TestCase):
    setUp = commute_fixtures.CommuteTagTests.setUp
    trip = commute_fixtures.CommuteTagTests.trip
    seed_origin = origin_fixtures.ParkingOriginTests.seed
    seed_destination = destination_fixtures.ParkingDestinationTests.seed
    telemetry = staticmethod(destination_fixtures.ParkingDestinationTests.telemetry)

    def rule(self):
        with patch('zeekr_control.commute_tags.time.time', return_value=(self.start-1000)/1000):
            return self.tags.update('owner', 'car', dict(action='commute-save', revision=0,
                home=dict(latitude=31.2, longitude=121.4, radius_m=300),
                work=dict(latitude=31.21, longitude=121.41, radius_m=300)))

    def query(self, date):
        return next(e for e in self.tags.query('owner', 'car', date)['events'] if e['id']=='current')

    def test_origin_automatically_tags_and_preserves_evidence_and_manual_note(self):
        self.rule(); self.seed_origin()
        self.tags.update('owner','car',dict(action='save',event_id='current',tags=['接娃'],note='保留',revision=0))
        before=self.db.read_bytes()
        row=self.query('2026-10-06')
        self.assertTrue(row['automatic_commute'])
        self.assertEqual(row['tags'],['接娃','通勤'])
        self.assertEqual(row['note'],'保留')
        evidence=row['start_place_evidence']
        self.assertEqual(evidence['source'],'parking_inferred')
        self.assertEqual(evidence['sampling_gap_seconds'],34)
        self.assertEqual(row['commute_evidence']['start_place_evidence'],evidence)
        self.assertIsNone(self.tags.commute._endpoint('car',self.current,self.current+1200000,True))
        self.assertEqual(self.db.read_bytes(),before)

    def test_destination_automatically_tags_without_promoting_gps(self):
        self.rule(); self.seed_destination()
        before=self.db.read_bytes();row=self.query('2026-09-28')
        self.assertTrue(row['automatic_commute'])
        self.assertEqual(row['end_place_evidence']['sampling_gap_seconds'],30)
        self.assertEqual(row['commute_evidence']['end_place_evidence'],row['end_place_evidence'])
        self.assertIsNone(self.tags.commute._endpoint('car',self.start,self.end,False))
        self.assertEqual(self.db.read_bytes(),before)

    def test_background_collect_uses_parking_evidence_without_query(self):
        self.rule(); self.seed_origin()
        self.tags.commute.collect('owner','car',self.current+1200001)
        with self.tags.store.connect() as db:
            result=db.execute("SELECT result FROM commute_decisions WHERE event_id='current'").fetchone()
        self.assertEqual(result,('matched',))
        self.tags.update('owner','car',dict(action='commute-exclude',event_id='current'))
        self.tags.commute.collect('owner','car',self.current+1200001)
        self.assertFalse(self.query('2026-10-06')['automatic_commute'])

    def test_both_endpoints_can_use_independent_parking_evidence(self):
        self.rule();self.seed_origin()
        end=self.current+1200000;park=end+90000
        location=dict(self.location,latitude=31.2,longitude=121.4)
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE report_observations(vehicle TEXT,state_time INTEGER,observed_at INTEGER,normalized_payload TEXT,decoder_version TEXT)')
            raw=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='current'").fetchone()[0])
            raw['end_location']=location
            raw['report_v2'].update(end=self.telemetry(end),parking=self.telemetry(park))
            db.execute("UPDATE monitor_events SET summary=? WHERE id='current'",(json.dumps(raw),))
            db.execute("UPDATE observations SET location=? WHERE cache_key='current-1'",(json.dumps(location),))
            for t in range(end,park+1,30000):
                db.execute('INSERT INTO report_observations VALUES(?,?,?,?,?)',('car',t,t+1000,json.dumps(self.telemetry(t)),'fixture'))
                db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',('car','arrival-'+str(t),t,t+1000,30,json.dumps(location)))
        row=self.query('2026-10-06')
        self.assertTrue(row['automatic_commute'])
        self.assertEqual(row['commute_evidence']['direction'],'backward')
        self.assertEqual(row['start_place_evidence']['sampling_gap_seconds'],34)
        self.assertEqual(row['end_place_evidence']['sampling_gap_seconds'],30)

    def test_insufficient_parking_can_retry_when_evidence_arrives(self):
        self.rule();self.seed_destination()
        with sqlite3.connect(self.db) as db:
            samples=db.execute('SELECT * FROM report_observations').fetchall()
            db.execute('DELETE FROM report_observations')
        row=self.query('2026-09-28')
        self.assertFalse(row['automatic_commute'])
        self.assertEqual(row['commute_reason'],'insufficient')
        with sqlite3.connect(self.db) as db:db.executemany('INSERT INTO report_observations VALUES(?,?,?,?,?)',samples)
        self.assertTrue(self.query('2026-09-28')['automatic_commute'])

    def test_forged_event_evidence_cannot_replace_database_validation(self):
        self.rule();self.seed_destination()
        with sqlite3.connect(self.db) as db:db.execute('DELETE FROM report_observations')
        event=dict(self.event,end_place_evidence=dict(source='parking_inferred',sampling_gap_seconds=30,point=(31.21,121.41)))
        before=copy.deepcopy(event)
        self.assertEqual(self.tags.commute.decisions('owner','car',[event])['current'][0],'insufficient')
        self.assertEqual(event,before)

    def test_partial_stays_for_manual_review_even_with_matching_gps(self):
        effective=self.rule()['effective_at'];self.trip('current',effective+1000,(31.2,121.4),(31.21,121.41))
        with sqlite3.connect(self.db) as db:
            raw=json.loads(db.execute('SELECT summary FROM monitor_events').fetchone()[0]);raw['partial']=True
            db.execute('UPDATE monitor_events SET summary=?',(json.dumps(raw),))
        row=self.query('2026-09-28')
        self.assertFalse(row['automatic_commute'])
        self.assertTrue(row['partial'])
        self.assertEqual(row['commute_reason'],'insufficient')

    def test_history_preview_preserves_parking_provenance(self):
        self.seed_destination();self.rule()
        result=self.tags.update('owner','car',dict(action='commute-preview',date='2026-09-28',revision=1))
        self.assertEqual(result['rows'][0]['result'],'matched')
        self.assertEqual(result['rows'][0]['end_place_evidence']['sampling_gap_seconds'],30)

    def test_outside_rule_is_not_commute_even_when_parking_is_valid(self):
        self.seed_origin()
        with patch('zeekr_control.commute_tags.time.time',return_value=(self.start-1000)/1000):
            self.tags.update('owner','car',dict(action='commute-save',revision=0,
                home=dict(latitude=32,longitude=120,radius_m=300),work=dict(latitude=32.1,longitude=120.1,radius_m=300)))
        row=self.query('2026-10-06')
        self.assertFalse(row['automatic_commute'])
        self.assertEqual(row['commute_reason'],'outside')
        self.assertEqual(row['start_place_evidence']['sampling_gap_seconds'],34)
