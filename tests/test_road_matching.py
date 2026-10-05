"""Synthetic road networks; no vehicle identifiers, owner traces or HTTP downloads."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.road_network import build_network
from zeekr_control.road_matching import RoadMatcher

BASE = 1704067200000

def point(i, lon=121, lat=31):
    return dict(state_time=BASE+i*60000, observed_time=BASE+i*60000, longitude=lon,
                latitude=lat, trusted=True, plottable=True, coordinate_system='WGS84（社区解释）')

def route(points, segments=None):
    return dict(observations=points,segments=segments if segments is not None else [points],
                count=len(points),gaps=[],quality={},truncated=False)

def osm():
    return {'elements':[{'type':'node','id':1,'lon':121,'lat':31},
                        {'type':'node','id':2,'lon':121.001,'lat':31},
                        {'type':'node','id':3,'lon':121.001,'lat':31.001},
                        {'type':'way','id':1,'nodes':[1,2,3],
                         'tags':{'highway':'residential','oneway':'yes','name':'Synthetic road'}}]}

class RoadMatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)/'roads';self.directory.mkdir()
        self.db=self.directory/'region.sqlite3';build_network(osm(),self.db)
        self.matcher=RoadMatcher(self.directory)
    def test_actual_worker_keeps_road_corner_and_original_observations(self):
        original=route([point(0,121.0002,31),point(1,121.001,31.0008)])
        before=copy.deepcopy(original);result=self.matcher.enrich(original)
        self.assertEqual(original,before)
        self.assertEqual(result['observations'],before['observations'])
        m=result['road_matching'];self.assertEqual(m['status'],'matched');self.assertEqual(m['matched_indices'],[0,1])
        self.assertEqual(m['spans'],[[0,1]])
        self.assertTrue(any(abs(x-121.001)<1e-8 and abs(y-31)<1e-8 for line in m['lines'] for x,y in line))
    def test_existing_fragments_never_join_across_a_small_time_gap(self):
        pts=[point(0,121.0001),point(1,121.0004),point(2,121.001,31.0002),point(3,121.001,31.0008)]
        m=self.matcher.enrich(route(pts,[pts[:2],pts[2:]]))['road_matching']
        self.assertEqual(m['spans'],[[0,1],[2,3]])
    def test_no_route_backwards_on_oneway_is_partial_and_has_no_connector(self):
        m=self.matcher.enrich(route([point(0,121.001,31.0008),point(1,121.0002)]))['road_matching']
        self.assertEqual(m['lines'],[]);self.assertEqual(m['spans'],[]);self.assertEqual(m['status'],'partial');self.assertEqual(m['issues'],1)
    def test_untrusted_unplottable_and_unknown_coordinate_system_do_not_bridge(self):
        for changes in [dict(trusted=False),dict(plottable=False),dict(coordinate_system='GCJ-02（社区解释）'),dict(state_time=None)]:
            pts=[point(0,121.0001),point(1,121.0005),point(2,121.001,31.0002)];pts[1].update(changes)
            m=self.matcher.enrich(route(pts))['road_matching'];self.assertEqual(m['spans'],[])
    def test_absent_maps_is_fallback_and_does_not_create_files(self):
        absent=self.directory/'missing';m=RoadMatcher(absent).enrich(route([point(0),point(1)]))['road_matching']
        self.assertEqual(m['status'],'unavailable');self.assertFalse(absent.exists())
    def test_cache_is_reused_and_invalidates_after_map_change(self):
        r=route([point(0,121.0002),point(1,121.001,31.0008)])
        with patch('zeekr_control.road_matching.subprocess.run',wraps=subprocess.run) as run:
            self.matcher.enrich(r);self.matcher.enrich(r);self.assertEqual(run.call_count,1)
            build_network(osm(),self.db);self.matcher.enrich(r);self.assertEqual(run.call_count,2)
    def test_timeout_and_busy_are_nonfatal_without_caching_failure(self):
        r=route([point(0),point(1)])
        with patch('zeekr_control.road_matching.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',8)):
            self.assertEqual(self.matcher.enrich(r)['road_matching']['status'],'timeout')
        self.matcher.gate.acquire()
        try:self.assertEqual(self.matcher.enrich(r)['road_matching']['status'],'busy')
        finally:self.matcher.gate.release()
        self.assertNotEqual(self.matcher.enrich(r)['road_matching']['status'],'busy')
    def test_no_candidates_retains_sources_and_explains_fallback(self):
        r=route([point(0,122),point(1,122.001)]);m=self.matcher.enrich(r)['road_matching']
        self.assertEqual(m['status'],'unmatched');self.assertEqual(m['matched_indices'],[])
    def test_large_routes_return_limit_before_spawning(self):
        pts=[point(i) for i in range(1501)]
        with patch('zeekr_control.road_matching.subprocess.run') as run:
            self.assertEqual(self.matcher.enrich(route(pts))['road_matching']['status'],'limit');run.assert_not_called()
    def test_builder_filters_non_driving_ways_and_is_readonly_at_runtime(self):
        import sqlite3
        data=osm();data['elements'].append(dict(type='way',id=2,nodes=[3,1],tags={'highway':'footway'}));build_network(data,self.db)
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('select count(*) from roads').fetchone()[0],1)
        before=self.db.read_bytes();self.matcher.enrich(route([point(0),point(1,121.001,31.0008)]));self.assertEqual(self.db.read_bytes(),before)


class RoadMatchApiTests(unittest.TestCase):
    def test_tracks_enriches_outside_app_lock_and_preserves_trip_bounds(self):
        from zeekr_control.web import App
        from unittest.mock import Mock
        app=App.__new__(App)
        import threading
        app.lock=threading.RLock();app._local_vehicle=lambda archive:'car-a';app.trip_store=Mock()
        pts=[point(0),point(1,121.001)]
        raw=route(pts);app.trip_store.bounds.return_value=(BASE,BASE+60000)
        app.trip_store.tracks.between.return_value=raw
        def enrich(value):
            self.assertFalse(app.lock._is_owned());self.assertIs(value,raw)
            return dict(value,road_matching={'status':'unavailable'})
        app.road_matcher=Mock();app.road_matcher.enrich.side_effect=enrich
        result=app.tracks('2024-01-01',trip='synthetic')
        self.assertEqual(result['observations'],pts)
        app.trip_store.tracks.between.assert_called_once_with('car-a',BASE,BASE+60000,'2024-01-01')
        self.assertEqual(result['road_matching']['status'],'unavailable')

if __name__=='__main__':unittest.main()
