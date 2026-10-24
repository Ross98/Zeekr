"""Bounded local travel overview; synthetic observations only."""
import unittest
from unittest.mock import Mock
from zeekr_control.trip_overview import TripOverview, summarize
from zeekr_control.tracks import day_bounds

DAY=86400000
T=day_bounds('2026-10-20')[0]

def place(key,label=None):
    return dict(key=key,label=label or key,source='manual',issues=[],latitude=31,longitude=121)

def trip(identity,start,end,km=10,a='home',b='work'):
    return dict(id=identity,type='trip',start_time=start,end_time=end,duration_seconds=(end-start)/1000,
                distance_km=km,start_place=place(a),end_place=place(b),partial=False,private='SECRET')

def parked(identity,start,end,unknown=0,gaps=()):
    return dict(id=identity,type='parking',start_time=start,end_time=end,duration_seconds=(end-start)/1000,
                start_place=place('work'),end_place=place('work'),parking_status='parked',
                observation_quality={'unknown_seconds':unknown,'gaps_limited':False},
                observation_gaps=[dict(start_time=a,end_time=b) for a,b in gaps])

class OverviewTests(unittest.TestCase):
    def test_week_read_once_and_no_month_scan(self):
        timeline=Mock()
        timeline._records.return_value=([],{'history_quality':0})
        result=TripOverview(timeline).query('scope','car','2026-10-20',owner='owner',now=T+DAY)
        timeline._records.assert_called_once_with('scope','car','owner','2026-10-14','2026-10-20',now=T+DAY)
        self.assertEqual(len(result['days']),7)
        timeline.calendar.query.assert_not_called()

    def test_end_date_attribution_null_unknown_days_and_no_private_fields(self):
        row=trip('cross',T-60000,T+60000,2)
        missing=trip('missing',T+120000,T+180000,None)
        result=summarize([row,missing],'2026-10-20',T+DAY)
        self.assertEqual(result['days'][-1]['distance_km'],2)
        self.assertEqual(result['days'][-1]['trip_count'],2)
        self.assertEqual(result['days'][-1]['missing_distance_count'],1)
        self.assertIsNone(result['days'][0]['distance_km'])
        self.assertNotIn('latitude',str(result))
        self.assertNotIn('SECRET',str(result))

    def test_reverse_routes_merge_by_keys_not_similar_labels_and_use_median(self):
        rows=[trip('a',T+10000,T+70000,10),trip('b',T+80000,T+200000,20,'work','home'),trip('c',T+300000,T+900000,30)]
        different=trip('different',T+1000000,T+1100000,5,a='other-home')
        different['start_place']['label']='home'
        result=summarize(rows+[different],'2026-10-20',T+DAY)
        self.assertEqual(len(result['routes']),2)
        route=result['routes'][0]
        self.assertEqual(route['count'],3)
        self.assertEqual(route['median_distance_km'],20)
        self.assertEqual(route['median_duration_seconds'],120)
        self.assertEqual(route['dates'],['2026-10-20'])

    def test_shared_statistics_identity_merges_manual_and_commute_routes_and_arrivals(self):
        a=trip('a',T+10000,T+70000)
        b=trip('b',T+80000,T+200000,a='work-other',b='home-other')
        for row in (a,b):
            for side,canonical,label in (('start','home' if row is a else 'work','家' if row is a else '公司'),
                                         ('end','work' if row is a else 'home','公司' if row is a else '家')):
                row[side+'_place'].update(statistics_key='region:'+canonical,label=label)
        b['end_place']['source']='commute'
        parking=parked('parking',T+70000,T+170000)
        parking['end_place']['statistics_key']='region:work'
        result=summarize([a,b,parking],'2026-10-20',T+DAY)
        self.assertEqual(len(result['routes']),1)
        self.assertEqual(result['routes'][0]['count'],2)
        self.assertEqual(len(result['places']),2)
        work=next(p for p in result['places'] if p['key']=='region:work')
        self.assertEqual(work['arrivals'],1)
        self.assertEqual(work['observed_parking_seconds'],100)

    def test_unknown_and_conflicting_places_excluded_from_routes(self):
        row=trip('x',T+10000,T+60000)
        row['start_place']=place(None,'未知')
        other=trip('y',T+80000,T+90000)
        other['end_place']['issues']=['candidate_conflict']
        result=summarize([row,other],'2026-10-20',T+DAY)
        self.assertEqual(result['routes'],[])
        self.assertEqual(result['unknown_route_count'],2)

    def test_parking_subtracts_unknown_gaps_unions_overlaps_and_never_uses_trip_gap(self):
        rows=[trip('a',T+10000,T+60000),trip('b',T+500000,T+600000,a='work',b='home'),
              parked('p',T+100000,T+400000,60,[(T+200000,T+260000)]),
              parked('duplicate',T+100000,T+180000)]
        result=summarize(rows,'2026-10-20',T+DAY)
        work=next(p for p in result['places'] if p['key']=='work')
        self.assertEqual(work['observed_parking_seconds'],240)
        self.assertEqual(work['arrivals'],1)
        self.assertEqual(next(p for p in result['places'] if p['key']=='home')['observed_parking_seconds'],None)

    def test_candidate_and_truncated_unknown_parking_not_counted_as_confirmed(self):
        row=parked('p',T,T+100000,60)
        row['observation_quality']['gaps_limited']=True
        candidate=parked('c',T+200000,T+300000)
        candidate['parking_status']='candidate'
        result=summarize([row,candidate],'2026-10-20',T+DAY)
        p=result['places'][0]
        self.assertIsNone(p['observed_parking_seconds'])
        self.assertTrue(p['parking_incomplete'])
        self.assertEqual(p['arrivals'],0)

    def test_parking_clip_at_week_boundary_and_future_records_ignored(self):
        start=T-6*DAY
        row=parked('p',start-60000,start+60000)
        result=summarize([row,trip('future',T+DAY,T+2*DAY)],'2026-10-20',T+DAY-1)
        self.assertEqual(result['places'][0]['observed_parking_seconds'],60)
        self.assertEqual(result['trip_count'],0)

class OverviewHTTPTests(unittest.TestCase):
    def setUp(self):
        from test_web_server import WebServerTests
        for name in ('request','post','cleanup'):
            setattr(self,name,getattr(WebServerTests,name).__get__(self))
        WebServerTests.setUp(self)

    def test_read_route_uses_bounded_context_handler(self):
        self.app.insights=Mock(return_value={'days':[],'context':'safe'})
        code,result=self.request('GET','/api/trip-overview?date=2026-10-20')
        self.assertEqual(code,200)
        self.app.insights.assert_called_once_with('trip-overview','2026-10-20')
        self.assertEqual(self.request('GET','/api/trip-overview?date=2026-10-20',headers={'Host':'evil.invalid'})[0],403)
