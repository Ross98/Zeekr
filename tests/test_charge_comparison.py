"""Observed-SOC comparisons: no fabricated crossing times or gap bridges."""
import json
from pathlib import Path
import tempfile
import unittest

from zeekr_control.monitor import Monitor
from zeekr_control.tracks import day_bounds


def curve_point(stamp,soc,power=100,mode='dc',**changes):
    metric=lambda value:dict(value=value,validity='valid',state_time=stamp,field_time=stamp)
    point=dict(state_time=stamp,observed_at=stamp,soc=soc,charging=True,charging_mode=mode,
               power_kw=power,power_source='ac_ui' if mode=='ac' else 'dc_pile_ui',
               outside_temp=metric(20),inside_temp=metric(24),decoder_version='synthetic-v1',
               position={'secret':'NEVER-EXPORT'},vin='NEVER-EXPORT')
    point.update(changes);return point


def add_curve(database,identity,vehicle,points,partial=False):
    with Monitor(database).tracks.connect() as db:
        a,b=points[0],points[-1]
        summary=dict(start_time=a['state_time'],end_time=b['state_time'],duration_seconds=(b['state_time']-a['state_time'])/1000,
            start_soc=a['soc'],end_soc=b['soc'],soc_delta=b['soc']-a['soc'],partial=partial,
            report_v2={'start':a,'end':b,'profile_snapshot':{'battery_capacity_kwh':86}},vin='NEVER-EXPORT')
        db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                   (identity,vehicle,'charge_end',json.dumps(summary),'PRIVATE',b['state_time']))
        for point in points:
            db.execute('INSERT OR REPLACE INTO report_observations(vehicle,state_time,observed_at,decoder_version,normalized_payload) VALUES(?,?,?,?,?)',
                       (vehicle,point['state_time'],point['observed_at'],point['decoder_version'],json.dumps(point)))


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        from zeekr_control.charge_comparison import ChargeComparison
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'tracks.sqlite3';self.api=ChargeComparison(self.db)
        self.start,_=day_bounds('2026-07-12')

    def seed(self,a=None,b=None,partial=False):
        a=a or [curve_point(self.start+i*60000,soc) for i,soc in enumerate((20,30,40,50,60))]
        b=b or [curve_point(self.start+86400000+i*60000,soc,7,'ac') for i,soc in enumerate((30,40,50,60,70))]
        add_curve(self.db,'a','car',a,partial);add_curve(self.db,'b','car',b)

    def test_aligns_only_common_observed_soc_and_separates_modes_sources(self):
        self.seed();data=self.api.query('car','a','b')
        self.assertEqual(data['common'],{'low':30,'high':60,'has_span':True})
        self.assertEqual([p['soc'] for p in data['a']['points']],[30,40,50,60])
        self.assertEqual(data['a']['modes'],['dc']);self.assertEqual(data['b']['modes'],['ac'])
        self.assertEqual(data['a']['power_sources'],['dc_pile_ui'])
        self.assertEqual(data['a']['timing']['minimum_seconds'],180)
        self.assertEqual(data['b']['timing']['maximum_seconds'],180)
        self.assertNotIn('NEVER-EXPORT',json.dumps(data))

    def test_soc_plateaus_preserve_arrival_windows_and_elapsed_points(self):
        points=[curve_point(self.start+i*60000,s) for i,s in enumerate((30,30,40,50,60,60))]
        self.seed(a=points);data=self.api.query('car','a','b')['a']
        self.assertEqual(data['timing']['minimum_seconds'],180)
        self.assertEqual(data['timing']['maximum_seconds'],300)
        self.assertEqual([p['elapsed_seconds'] for p in data['points']][:2],[0,60])

    def test_missing_exact_boundary_is_not_interpolated(self):
        self.seed(a=[curve_point(self.start+i*60000,s) for i,s in enumerate((20,40,60))])
        row=self.api.query('car','a','b')['a']
        self.assertEqual(row['timing']['reason'],'boundary_not_observed')
        self.assertIsNone(row['timing']['minimum_seconds'])
        self.assertTrue(all(p['elapsed_seconds'] is None for p in row['points']))

    def test_gap_breaks_curves_and_suppresses_duration_estimate(self):
        self.seed(a=[curve_point(self.start+i*600000,s) for i,s in enumerate((30,40,50,60))])
        row=self.api.query('car','a','b')['a']
        self.assertEqual(row['timing']['reason'],'gaps_or_reset')
        self.assertEqual(len({p['segment'] for p in row['points']}),4)

    def test_soc_regression_decoder_change_and_unknown_state_split(self):
        points=[curve_point(self.start+i*60000,s) for i,s in enumerate((30,40,35,50,60))]
        points[3]['decoder_version']='changed'
        points[4]['charging']=None
        self.seed(a=points)
        row=self.api.query('car','a','b')['a']
        self.assertEqual(row['quality']['excluded'],1)
        self.assertGreaterEqual(row['quality']['segments'],3)

    def test_unverified_power_stale_and_invalid_temperatures_are_gaps(self):
        points=[curve_point(self.start+i*60000,s) for i,s in enumerate((30,40,50,60))]
        points[1]['power_source']='unverified'
        points[1]['outside_temp']['field_time']-=600000
        points[2]['inside_temp']['validity']='stale'
        self.seed(a=points);row=self.api.query('car','a','b')['a']
        self.assertIsNone(row['points'][1]['power_kw'])
        self.assertIsNone(row['points'][1]['outside_temp'])
        self.assertIsNone(row['points'][2]['inside_temp'])
        self.assertNotEqual(row['points'][0]['lines']['power_kw'],row['points'][2]['lines']['power_kw'])

    def test_partial_sessions_keep_label_and_only_compare_observed_subrange(self):
        self.seed(partial=True);row=self.api.query('car','a','b')['a']
        self.assertTrue(row['event']['partial'])
        self.assertEqual(row['timing']['minimum_seconds'],180)

    def test_no_common_range_is_explicit(self):
        self.seed(b=[curve_point(self.start+86400000+i*60000,s) for i,s in enumerate((80,90))])
        data=self.api.query('car','a','b')
        self.assertIsNone(data['common']);self.assertEqual(data['a']['points'],[])

    def test_missing_table_or_legacy_event_has_no_invented_series(self):
        self.seed()
        with self.api.events.connect() as db:self.assertTrue(db)
        import sqlite3
        with sqlite3.connect(self.db) as db:db.execute('DROP TABLE report_observations')
        data=self.api.query('car','a','b')
        self.assertIsNone(data['common']);self.assertEqual(data['a']['quality']['eligible'],0)

    def test_scope_and_selection_validation(self):
        self.seed()
        for vehicle,a,b in [('other','a','b'),('car','a','a'),('car','current','a'),('car','../a','b')]:
            with self.assertRaises(ValueError):self.api.query(vehicle,a,b)
        self.assertEqual(len(self.api.options('car','2026-07-12')['events']),2)
        self.assertEqual(self.api.options('other','2026-07-12')['events'],[])

    def test_downsampling_preserves_global_endpoints_peak_and_never_merges_segments(self):
        points=[curve_point(self.start+i*240000,30+i/1000,200 if i==877 else 100) for i in range(1001)]
        self.seed(a=points,b=[curve_point(self.start+400000000+i*60000,s) for i,s in enumerate((30,31))])
        row=self.api.query('car','a','b')['a']
        self.assertLessEqual(len(row['points']),600)
        self.assertEqual(row['points'][0]['soc'],30);self.assertEqual(row['points'][-1]['soc'],31)
        self.assertEqual(max(p['power_kw'] for p in row['points']),200)
        self.assertEqual(len({p['lines']['power_kw'] for p in row['points']}),len(row['points']))

    def test_invalid_row_is_counted_and_breaks_continuity(self):
        self.seed()
        import sqlite3
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE report_observations SET normalized_payload=? WHERE vehicle=? AND state_time=?',
                       ('not-json','car',self.start+120000))
        row=self.api.query('car','a','b')['a']
        self.assertEqual(row['quality']['invalid'],1)
        self.assertEqual(row['timing']['reason'],'gaps_or_reset')


if __name__=='__main__':unittest.main()
