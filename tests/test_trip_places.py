import json
import math
import sqlite3
import unittest

from tests import test_commute_tags as fixtures
from zeekr_control.trip_places import cluster_endpoints, RADIUS_M


def point(meters):
    return (31.2+math.degrees(meters/6371000),121.4)


class PlaceClusterTests(unittest.TestCase):
    def endpoint(self, identity, meters, side='start', stamp=1):
        return dict(event_id=identity, side=side, time=stamp, point=point(meters))

    def test_radius_boundary_and_shared_start_end(self):
        result=cluster_endpoints([self.endpoint('a',0),self.endpoint('b',150,'end',2),self.endpoint('c',150.1,'end',3)])
        self.assertEqual(RADIUS_M,150)
        self.assertEqual(len(result['places']),2)
        first=result['places'][0]
        self.assertEqual((first['departures'],first['arrivals']),(1,1))
        self.assertEqual(result['assignments']['a']['start'],result['assignments']['b']['end'])

    def test_fixed_center_prevents_transitive_chains_and_is_order_independent(self):
        rows=[self.endpoint('a',0),self.endpoint('b',140,stamp=2),self.endpoint('c',280,stamp=3)]
        a=cluster_endpoints(rows);b=cluster_endpoints(list(reversed(rows)))
        self.assertEqual(a,b)
        self.assertEqual(len(a['places']),2)
        self.assertEqual(a['assignments']['a'],a['assignments']['b'])
        self.assertNotEqual(a['assignments']['b'],a['assignments']['c'])

    def test_nearest_center_wins_when_ranges_overlap(self):
        result=cluster_endpoints([self.endpoint('a',0),self.endpoint('b',200,stamp=2),self.endpoint('c',130,stamp=3)])
        self.assertEqual(result['assignments']['b'],result['assignments']['c'])

    def test_antimeridian_points_are_neighbours(self):
        rows=[dict(event_id='a',side='start',time=1,point=(1,179.9997)),dict(event_id='b',side='end',time=2,point=(1,-179.9997))]
        self.assertEqual(len(cluster_endpoints(rows)['places']),1)


class TripPlaceQueryTests(unittest.TestCase):
    setUp=fixtures.CommuteTagTests.setUp
    trip=fixtures.CommuteTagTests.trip
    def test_monthly_place_counts_routes_unknown_and_readonly(self):
        self.trip('a',self.start,point(0),point(1000))
        self.trip('b',self.start+3600000,point(80),point(1070))
        self.trip('unknown',self.start+7200000,point(0),point(1000),trusted=False)
        self.trip('foreign',self.start+10800000,point(5000),point(6000),vehicle='other')
        before=self.db.read_bytes()
        result=self.tags.query('owner','car','2026-09-28')['place_statistics']
        self.assertEqual(len(result['places']),2)
        self.assertEqual([p['departures'] for p in result['places']],[2,0])
        self.assertEqual([p['arrivals'] for p in result['places']],[0,2])
        self.assertEqual(result['routes'][0]['count'],2)
        self.assertEqual((result['unknown_departures'],result['unknown_arrivals']),(1,1))
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse(self.tags.store.path.exists())
        foreign=self.tags.query('owner','other','2026-09-28')['place_statistics']
        self.assertEqual(len(foreign['places']),2)
        self.assertEqual(sum(p['departures'] for p in foreign['places']),1)

    def test_partial_missing_start_still_counts_valid_arrival(self):
        self.trip('a',self.start,point(0),point(1000))
        with sqlite3.connect(self.db) as db:
            raw=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='a'").fetchone()[0])
            raw['start_time']=None;raw['partial']=True
            db.execute("UPDATE monitor_events SET summary=? WHERE id='a'",(json.dumps(raw),))
        result=self.tags.query('owner','car','2026-09-28')
        self.assertTrue(result['events'][0]['partial'])
        self.assertIsNone(result['events'][0]['start_place'])
        self.assertIsNotNone(result['events'][0]['end_place'])
        self.assertEqual(result['place_statistics']['unknown_departures'],1)

    def test_invalid_coordinate_system_and_zero_coordinates_are_unknown(self):
        self.trip('a',self.start,point(0),point(1000))
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE observations SET location=?',(json.dumps(dict(latitude=0,longitude=0,trusted=True,plottable=True,coordinate_system='WGS84（社区解释）')),))
        self.assertEqual(self.tags.query('owner','car','2026-09-28')['place_statistics']['places'],[])

    def test_single_observation_cannot_establish_two_endpoints(self):
        self.trip('short',self.start,point(0),point(20))
        with sqlite3.connect(self.db) as db:
            raw=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='short'").fetchone()[0])
            raw['end_time']=self.start+60000;raw['duration_seconds']=60
            db.execute("UPDATE monitor_events SET summary=? WHERE id='short'",(json.dumps(raw),))
            db.execute("DELETE FROM observations WHERE cache_key='short-1'")
        result=self.tags.query('owner','car','2026-09-28')['place_statistics']
        self.assertEqual(result['places'],[])
        self.assertEqual(result['unknown_arrivals'],1)

    def test_old_and_wrong_coordinate_system_are_not_grouped(self):
        self.trip('a',self.start,point(0),point(1000))
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE observations SET state_time=state_time+180000 WHERE cache_key='a-0'")
            raw=json.loads(db.execute("SELECT location FROM observations WHERE cache_key='a-1'").fetchone()[0])
            raw['coordinate_system']='GCJ02'
            db.execute("UPDATE observations SET location=? WHERE cache_key='a-1'",(json.dumps(raw),))
        result=self.tags.query('owner','car','2026-09-28')['place_statistics']
        self.assertEqual(result['places'],[])

    def test_empty_month_returns_explicit_unknown_counts(self):
        result=self.tags.query('owner','car','2026-08-01')['place_statistics']
        self.assertEqual(result['places'],[])
        self.assertEqual(result['unknown_departures'],0)
