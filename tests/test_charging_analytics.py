import json
from pathlib import Path
import tempfile
import unittest

from zeekr_control.charging_analytics import ChargingAnalytics
from zeekr_control.monitor import Monitor


BASE = 1704067200000


def sample(at, soc, power, mode='ac', *, observed=None, charging=True, decoder='we86-v2-ac'):
    voltage = 220 if mode == 'ac' else 400
    current = power * 1000 / voltage if power is not None else None
    return {
        'schema_version': 2, 'decoder_version': decoder, 'state_time': at,
        'observed_at': at if observed is None else observed, 'soc': soc,
        'charging': charging, 'charging_mode': mode, 'power_kw': power,
        'power_source': 'ac_ui' if mode == 'ac' else 'dc_pile_ui',
        'ac_voltage': {'value': voltage if mode == 'ac' else None, 'validity': 'valid'},
        'ac_current': {'value': current if mode == 'ac' else None, 'validity': 'valid'},
        'voltage': {'value': voltage if mode == 'dc' else None, 'validity': 'valid'},
        'current': {'value': current if mode == 'dc' else None, 'validity': 'valid'},
        'secret': 'NEVER-PUBLIC',
    }


class ChargingAnalyticsTests(unittest.TestCase):
    def test_dense_curve_keeps_metric_gap_and_independent_soc_continuity(self):
        points=[sample(BASE+i*1000,40+i/100,7) for i in range(1001)]
        points[500]['power_kw']=None
        self.insert_observations('car-a',points)
        self.insert_event('dense','car-a',BASE,points[-1]['state_time'])
        result=self.analytics.series('car-a','dense','power-soc')
        self.assertTrue(result['has_gaps'])
        self.assertLessEqual(result['display_count'],600)
        before=[p for p in result['points'] if p['time']<points[500]['state_time']][-1]
        after=[p for p in result['points'] if p['time']>points[500]['state_time']][0]
        self.assertNotEqual(before['lines']['power_kw'],after['lines']['power_kw'])
        self.assertEqual(before['lines']['soc'],after['lines']['soc'])

    def test_electrical_downsampling_preserves_current_peak_as_well_as_voltage(self):
        points=[sample(BASE+i*1000,40,7) for i in range(1001)]
        points[500]['ac_current']['value']=100
        self.insert_observations('car-a',points)
        self.insert_event('electrical','car-a',BASE,points[-1]['state_time'])
        result=self.analytics.series('car-a','electrical','electrical')
        self.assertEqual(max(p['current'] for p in result['points']),100)

    def test_more_metric_gaps_than_display_slots_never_join_across_missing_power(self):
        points=[sample(BASE+i*1000,40+i/100,None if i%3==1 else 7) for i in range(1501)]
        self.insert_observations('car-a',points)
        self.insert_event('many-gaps','car-a',BASE,points[-1]['state_time'])
        result=self.analytics.series('car-a','many-gaps','power-soc')
        self.assertLessEqual(result['display_count'],600)
        valid=[p for p in result['points'] if p['power_kw'] is not None]
        for left,right in zip(valid,valid[1:]):
            low,high=int((left['time']-BASE)/1000),int((right['time']-BASE)/1000)
            if any(i%3==1 for i in range(low+1,high)):
                self.assertNotEqual(left['lines']['power_kw'],right['lines']['power_kw'])
        self.assertEqual({p['lines']['soc'] for p in result['points']},{1})

    def test_cancelled_statistics_stops_before_remaining_event_decodes(self):
        from unittest.mock import patch
        from zeekr_control.analysis_cancel import cancellation_scope,AnalysisCancelled
        self.insert_event('first','car-a',BASE,BASE+60000)
        self.insert_event('second','car-a',BASE,BASE+120000)
        flag=[False];seen=[];decode=json.loads
        def cancel_after_decode(encoded,*args,**kwargs):
            result=decode(encoded,*args,**kwargs);seen.append(1);flag[0]=True
            return result
        with cancellation_scope(lambda:flag[0]),patch('zeekr_control.charging_analytics.json.loads',side_effect=cancel_after_decode):
            with self.assertRaises(AnalysisCancelled):
                self.analytics.statistics('car-a',7,'all',now=BASE+86400000)
        self.assertEqual(len(seen),1)

    def test_already_cancelled_charging_read_does_not_open_database(self):
        from unittest.mock import patch
        from zeekr_control.analysis_cancel import cancellation_scope,AnalysisCancelled
        flag=[False]
        reads=(lambda:self.analytics.session('car-a','current'),
               lambda:self.analytics.series('car-a','current','power-soc'),
               lambda:self.analytics.process('car-a','current','power-soc'),
               lambda:self.analytics.statistics('car-a',7,'all',now=BASE))
        with cancellation_scope(lambda:flag[0]),patch('zeekr_control.charging_analytics.sqlite3.connect') as connect:
            flag[0]=True
            for read in reads:
                with self.assertRaises(AnalysisCancelled):read()
            connect.assert_not_called()

    def test_cancelled_process_stops_decoding_and_releases_snapshot_and_job_slot(self):
        import sqlite3
        import threading
        from unittest.mock import patch
        from zeekr_control.analysis_jobs import AnalysisJobs
        points=[sample(BASE+i*1000,40+i/100,7) for i in range(30)]
        self.insert_observations('car-a',points)
        self.insert_event('cancel','car-a',BASE,points[-1]['state_time'])
        jobs=AnalysisJobs();entered=threading.Event();release=threading.Event();exited=threading.Event()
        self.addCleanup(release.set)
        decode=json.loads;seen=[]
        def read_point(encoded,*args,**kwargs):
            result=decode(encoded,*args,**kwargs)
            if isinstance(result,dict) and result.get('power_source')=='ac_ui':
                seen.append(result['state_time'])
                if len(seen)==1:entered.set();release.wait(2)
            return result
        def read():
            try:return 200,self.analytics.process('car-a','cancel','power-soc')
            finally:exited.set()
        with patch('zeekr_control.charging_analytics.json.loads',side_effect=read_point):
            ticket=jobs.submit('owner',read,key='charging')
            self.assertTrue(entered.wait(1))
            jobs.cancel(ticket,'owner');release.set()
            self.assertTrue(exited.wait(1))
        self.assertEqual(len(seen),1)
        with sqlite3.connect(self.path,timeout=.2) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE monitor_events SET message='cleanup verified' WHERE id='cancel'")
        acquired=[]
        try:
            for _ in range(2):
                acquired.append(jobs.slots.acquire(timeout=1))
                self.assertTrue(acquired[-1])
        finally:
            for value in acquired:
                if value:jobs.slots.release()

    def test_sqlite_scan_observes_analysis_cancellation(self):
        import sqlite3
        from zeekr_control.analysis_cancel import cancellation_scope
        cancelled=[False]
        with cancellation_scope(lambda:cancelled[0]),self.analytics._connect() as db:
            cancelled[0]=True
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<1000000) SELECT sum(x) FROM n').fetchone()

    def test_process_summary_and_curve_share_one_snapshot_during_collection_update(self):
        import sqlite3
        from unittest.mock import patch
        points=[sample(BASE+i*60000,40+i,7) for i in range(3)]
        self.insert_observations('car-a',points[:2])
        state={'charge':{'report_start':points[0],'samples':points[:2],'partial':True}}
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('INSERT OR REPLACE INTO monitor_state VALUES(?,?)',('car-a',json.dumps(state)))
        session=self.analytics.session
        def read_then_update(*args,**kwargs):
            result=session(*args,**kwargs)
            state['charge']['samples']=points
            with sqlite3.connect(self.path) as db:
                db.execute('UPDATE monitor_state SET payload=? WHERE vehicle=?',(json.dumps(state),'car-a'))
                p=points[-1]
                db.execute('INSERT INTO report_observations VALUES(?,?,?,?,?)',
                           ('car-a',p['state_time'],p['observed_at'],json.dumps(p),p['decoder_version']))
            return result
        with patch.object(self.analytics,'session',side_effect=read_then_update):
            result=self.analytics.process('car-a','current','power-soc')
        self.assertEqual(result['session']['end_time'],points[1]['state_time'])
        self.assertEqual(result['series']['points'][-1]['time'],result['session']['end_time'])
        next_result=self.analytics.process('car-a','current','power-soc')
        self.assertEqual(next_result['session']['end_time'],points[-1]['state_time'])
        self.assertEqual(next_result['series']['points'][-1]['time'],points[-1]['state_time'])

    def test_unreadable_observation_breaks_curve_instead_of_joining_neighbors(self):
        points=[sample(BASE+i*60000,20+i,7) for i in range(3)]
        self.insert_observations('car-a',points)
        self.insert_event('broken','car-a',BASE,BASE+120000)
        for encoded in ('not-json','[]','['*1500+'0'+']'*1500):
            with self.subTest(encoded=encoded[:10]),Monitor(self.path).tracks.connect() as db:
                db.execute('UPDATE report_observations SET normalized_payload=? WHERE state_time=?',
                           (encoded,BASE+60000))
            series=self.analytics.series('car-a','broken','power-soc')
            self.assertEqual(series['raw_count'],2)
            self.assertTrue(series['has_gaps'])
            self.assertNotEqual(series['points'][0]['segment_id'],series['points'][1]['segment_id'])

    def test_invalid_observation_time_is_skipped_and_breaks_curve(self):
        points=[sample(BASE+i*60000,20+i,7) for i in range(3)]
        self.insert_observations('car-a',points)
        self.insert_event('broken','car-a',BASE,BASE+120000)
        for field,value in (('state_time',None),('state_time',{}),('observed_at',[]),
                            ('state_time',BASE+61000),('observed_at',BASE+700000)):
            payload=dict(points[1],**{field:value})
            with self.subTest(field=field,value=value),Monitor(self.path).tracks.connect() as db:
                db.execute('UPDATE report_observations SET normalized_payload=? WHERE state_time=?',
                           (json.dumps(payload),BASE+60000))
            series=self.analytics.series('car-a','broken','power-soc')
            self.assertEqual(series['raw_count'],2)
            self.assertTrue(series['has_gaps'])

    def test_deep_charge_summary_is_rejected_without_hiding_valid_statistics(self):
        self.insert_event('valid','car-a',BASE,BASE+120000)
        self.insert_event('bad','car-a',BASE,BASE+180000)
        deep='{"extra":'+('['*1500)+'0'+(']'*1500)+'}'
        with Monitor(self.path).tracks.connect() as db:
            db.execute("UPDATE monitor_events SET summary=? WHERE id='bad'",(deep,))
            db.execute('INSERT OR REPLACE INTO monitor_state VALUES(?,?)',('car-a',deep))
        for selection in ('bad','current'):
            with self.subTest(selection=selection),self.assertRaisesRegex(ValueError,'无法读取'):
                self.analytics.session('car-a',selection)
        stats=self.analytics.statistics('car-a',7,'all',now=BASE+86400000)
        self.assertEqual([row['id'] for row in stats['records']],['valid'])
        self.assertIsNone(stats['current'])

    def test_session_and_statistics_agree_on_unknown_or_conflicting_completeness(self):
        self.insert_event('uncertain','car-a',BASE,BASE+3600000)
        for missing in (False,True):
            with self.subTest(missing=missing),Monitor(self.path).tracks.connect() as db:
                encoded=db.execute("SELECT summary FROM monitor_events WHERE id='uncertain'").fetchone()[0]
                summary=json.loads(encoded)
                if missing:
                    summary.pop('partial',None);summary['report_v2'].pop('partial',None)
                else:
                    summary['partial']=False;summary['report_v2']['partial']=True
                db.execute("UPDATE monitor_events SET summary=? WHERE id='uncertain'",(json.dumps(summary),))
            self.assertTrue(self.analytics.session('car-a','uncertain')['partial'])
            self.assertEqual(self.analytics.statistics('car-a',7,'all',now=BASE+86400000)['summary']['complete_count'],0)

    def test_active_charge_with_missing_partial_flag_is_not_claimed_complete(self):
        point=sample(BASE,40,6)
        state={'charge':{'report_start':point,'samples':[point]}}
        with Monitor(self.path).tracks.connect() as db:
            db.execute('INSERT INTO monitor_state VALUES (?,?)',('car-a',json.dumps(state)))
        self.assertTrue(self.analytics.session('car-a','current')['partial'])

    def test_unrecognized_or_malformed_mode_is_unknown_without_crashing(self):
        for index,mode in enumerate(([], {'mode':'ac'}, 7, 'new-enum')):
            with self.subTest(mode=mode):
                identity='mode'+str(index)
                self.insert_event(identity,'car-a',BASE,BASE+3600000,mode=mode)
                self.assertEqual(self.analytics.session('car-a',identity)['mode'],'unknown')
        statistics=self.analytics.statistics('car-a',7,'all',now=BASE+86400000)
        self.assertEqual(statistics['summary']['ended_count'],4)
        self.assertTrue(all(row['mode']=='unknown' for row in statistics['records']))

    def test_nonobject_charge_summary_returns_controlled_read_error(self):
        self.insert_event('damaged','car-a',BASE,BASE+3600000)
        with Monitor(self.path).tracks.connect() as db:
            db.execute("UPDATE monitor_events SET summary='[]' WHERE id='damaged'")
        with self.assertRaisesRegex(ValueError,'无法读取'):
            self.analytics.session('car-a','damaged')

    def test_known_short_sampling_gap_breaks_chart_segments(self):
        points=[sample(BASE+i*60000,20+i,7) for i in range(4)]
        points[2]['sampling_gap_before']=True
        self.insert_observations('car-a',points)
        self.insert_event('gap','car-a',BASE,BASE+180000)
        result=self.analytics.series('car-a','gap','power-soc')
        self.assertEqual(result['raw_count'],4)
        self.assertTrue(result['has_gaps'])
        self.assertEqual([row['point_count'] for row in result['segments']],[2,2])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'tracks.sqlite3'
        Monitor(self.path)
        self.analytics = ChargingAnalytics(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def insert_observations(self, vehicle, rows):
        with Monitor(self.path).tracks.connect() as db:
            for row in rows:
                db.execute('INSERT INTO report_observations VALUES (?,?,?,?,?)', (
                    vehicle, row['state_time'], row['observed_at'], json.dumps(row),
                    row['decoder_version']))

    def insert_event(self, event_id, vehicle, start, end, *, mode='ac', partial=False,
                     capacity=86, metrics=None):
        report = {'schema_version': 2, 'decoder_version': 'we86-v2-ac',
                  'kind': 'charge_end', 'start_time': start, 'end_time': end,
                  'partial': partial, 'start': {'soc': 20, 'charging_mode': mode},
                  'end': {'soc': 80, 'charging_mode': mode},
                  'metrics': metrics or {'duration_seconds': (end-start)/1000,
                                         'soc_delta': 60, 'estimated_kwh': 51.6}}
        summary = {'start_time': start, 'end_time': end,
                   'duration_seconds': (end-start)/1000, 'start_soc': 20,
                   'end_soc': 80, 'soc_delta': 60, 'partial': partial,
                   'battery_capacity_kwh': capacity, 'report_v2': report,
                   'private': 'NEVER-PUBLIC'}
        with Monitor(self.path).tracks.connect() as db:
            db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                       (event_id, vehicle, 'charge_end', json.dumps(summary), 'PRIVATE', end))

    def test_historical_session_and_series_are_vehicle_scoped_and_whitelisted(self):
        self.insert_event('event-a', 'car-a', BASE, BASE+600000)
        self.insert_event('event-b', 'car-b', BASE, BASE+600000)
        self.insert_observations('car-a', [
            sample(BASE, 20, 6.0), sample(BASE+60000, 21, 6.2),
            sample(BASE+400000, 30, 6.4), sample(BASE+460000, 31, 6.3),
        ])
        session = self.analytics.session('car-a', 'event-a')
        self.assertEqual(session['id'], 'event-a')
        self.assertEqual(session['mode'], 'ac')
        with self.assertRaises(ValueError):
            self.analytics.session('car-a', 'event-b')
        series = self.analytics.series('car-a', 'event-a', 'power-soc')
        self.assertEqual(series['raw_count'], 4)
        self.assertEqual(len(series['segments']), 2)
        self.assertTrue(series['has_gaps'])
        self.assertEqual(set(series['points'][0]), {'time', 'soc', 'power_kw', 'segment_id', 'quality', 'lines'})
        self.assertNotIn('NEVER-PUBLIC', json.dumps(series))

    def test_current_session_uses_monitor_state_bounds(self):
        rows = [sample(BASE, 40, 6.0), sample(BASE+60000, 41, 6.1)]
        self.insert_observations('car-a', rows)
        state = {'charge': {'report_start': rows[0], 'samples': rows, 'partial': True}, 'last': {}}
        with Monitor(self.path).tracks.connect() as db:
            db.execute('INSERT OR REPLACE INTO monitor_state VALUES (?,?)', ('car-a', json.dumps(state)))
        result = self.analytics.session('car-a', 'current')
        self.assertEqual(result['status'], 'active')
        self.assertTrue(result['partial'])
        self.assertEqual(result['start_time'], BASE)
        self.assertEqual(self.analytics.series('car-a', 'current', 'electrical')['raw_count'], 2)
        process = self.analytics.process('car-a', 'current', 'power-soc')
        self.assertEqual(process['session']['status'], 'active')
        self.assertEqual(process['series']['raw_count'], 2)

    def test_legacy_session_remaining_minutes_exclude_startup_placeholder(self):
        for minutes in (2046, 2047, 33, 0):
            end = sample(BASE, 40, 6)
            end['remaining_minutes'] = minutes
            state = {'charge': {'report_start': end, 'samples': [end], 'partial': True}}
            with Monitor(self.path).tracks.connect() as db:
                db.execute('INSERT OR REPLACE INTO monitor_state VALUES (?,?)',
                           ('car-a', json.dumps(state)))
            self.assertEqual(self.analytics.session('car-a', 'current')['remaining_minutes'],
                             None if minutes in (2046, 2047) else minutes)

    def test_statistics_include_partial_observations_and_retain_complete_subtotal(self):
        day = 86400000
        complete = {'duration_seconds': 3600, 'soc_delta': 60, 'estimated_kwh': 51.6,
                    'sampled_peak_kw': 6.5, 'average_power_kw': 6.2,
                    'power_sample_count': 10, 'power_covered_seconds': 3200,
                    'power_coverage': .89}
        self.insert_event('complete-ac', 'car-a', BASE, BASE+3600000, metrics=complete)
        self.insert_event('partial-dc', 'car-a', BASE+day, BASE+day+1800000,
                          mode='dc', partial=True, metrics={'duration_seconds': 1800,
                          'soc_delta': 60, 'estimated_kwh': 51.6, 'sampled_peak_kw': 80})
        self.insert_event('other-car', 'car-b', BASE, BASE+3600000, metrics=complete)
        result = self.analytics.statistics('car-a', 30, 'all', now=BASE+2*day)
        self.assertEqual(result['summary']['ended_count'], 2)
        self.assertEqual(result['summary']['complete_count'], 1)
        self.assertEqual(result['summary']['partial_count'], 1)
        self.assertEqual(result['summary']['estimated_kwh'], 103.2)
        self.assertEqual(result['summary']['duration_seconds'], 5400)
        self.assertEqual(result['summary']['partial_energy_count'], 1)
        self.assertEqual(result['summary']['included_energy_count'], 2)
        self.assertEqual(result['summary']['excluded_energy_count'], 0)
        self.assertEqual(result['summary']['complete_duration_seconds'], 3600)
        self.assertEqual(len(result['records']), 2)
        self.assertEqual(self.analytics.statistics('car-a', 30, 'ac', now=BASE+2*day)['summary']['ended_count'], 1)
        self.assertEqual(self.analytics.statistics('car-a', 30, 'dc', now=BASE+2*day)['summary']['ended_count'], 1)

    def test_invalid_inputs_and_empty_state(self):
        for bad in ('', '../secret', 'x'*129):
            with self.assertRaises(ValueError):
                self.analytics.session('car-a', bad)
        with self.assertRaises(ValueError):
            self.analytics.series('car-a', 'current', 'wrong')
        with self.assertRaises(ValueError):
            self.analytics.statistics('car-a', 8, 'all')
        self.assertEqual(self.analytics.statistics('car-a', 7, 'all')['summary']['ended_count'], 0)
        self.assertEqual(self.analytics.session('car-a', 'current')['status'], 'empty')

    def test_downsampling_keeps_peak_endpoints_and_gap_edges(self):
        rows = [sample(BASE+i*60000, 20+i//100, 99 if i == 777 else 6+i/1000)
                for i in range(1001)]
        rows[501]['state_time'] += 300000
        rows[501]['observed_at'] += 300000
        for index in range(502, len(rows)):
            rows[index]['state_time'] += 300000
            rows[index]['observed_at'] += 300000
        self.insert_event('long-event', 'car-a', rows[0]['state_time'], rows[-1]['state_time'])
        self.insert_observations('car-a', rows)
        result = self.analytics.series('car-a', 'long-event', 'power-soc')
        self.assertEqual(result['display_count'], 600)
        self.assertTrue(result['downsampled'])
        self.assertEqual(result['points'][0]['time'], rows[0]['state_time'])
        self.assertEqual(result['points'][-1]['time'], rows[-1]['state_time'])
        self.assertIn(99, [point['power_kw'] for point in result['points']])
        displayed_times = {point['time'] for point in result['points']}
        self.assertIn(rows[500]['state_time'], displayed_times)
        self.assertIn(rows[501]['state_time'], displayed_times)

    def test_many_gap_boundaries_do_not_evict_endpoint_or_peak(self):
        points=[{'time':BASE+i*60000,'segment_id':i//2,'power_kw':99 if i==777 else 6}
                for i in range(1001)]
        selected=self.analytics._downsample(points,600)
        self.assertEqual(len(selected),600)
        self.assertEqual(selected[0]['time'],points[0]['time'])
        self.assertEqual(selected[-1]['time'],points[-1]['time'])
        self.assertIn(99,[point['power_kw'] for point in selected])
        self.assertEqual(len(points),1001)


if __name__ == '__main__':
    unittest.main()
