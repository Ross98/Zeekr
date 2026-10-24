"""Damaged historical comparisons must not block new event archival."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from zeekr_control.report_history import compare

NOW = 1704067200000


def trip():
    return {'schema_version':2, 'decoder_version':'we86-v1', 'kind':'trip_end', 'partial':False,
            'start_time':NOW, 'end_time':NOW+600000, 'quality':{},
            'metrics':{'distance_km':10, 'duration_seconds':600, 'average_speed_kmh':60}}


class HistoricalComparisonBoundaryTests(unittest.TestCase):
    def test_decoder_changed_current_report_cannot_compare_with_complete_history(self):
        for index in range(5):self.insert('good'+str(index),{'report_v2':self.historical()})
        current=trip();current['quality']['decoder_changed_mid_session']=True
        result=compare(self.db,'car',current)
        self.assertFalse(result['available'])
        self.assertEqual(result['excluded'],{'current_ineligible':1})

    def test_ineligible_current_report_does_not_read_optional_history(self):
        from unittest.mock import patch
        for reason in ('partial','upgrade_mid_session','decoder_changed_mid_session'):
            with self.subTest(reason=reason):
                current=trip()
                if reason=='partial':current['partial']=True
                else:current['quality'][reason]=True
                with patch('zeekr_control.report_history._candidates',side_effect=AssertionError('unneeded history read')):
                    result=compare(self.db,'car',current)
                self.assertFalse(result['available'])

    def test_real_report_builder_decoder_change_suppresses_comparison_only(self):
        from zeekr_control.monitor import Monitor
        from zeekr_control.report_telemetry import normalize
        from test_monitor import sample
        with tempfile.TemporaryDirectory() as directory:
            monitor=Monitor(Path(directory)/'tracks.sqlite3')
            start=normalize(sample(0,km=100,soc=80),NOW)
            end=normalize(sample(600,km=110,soc=70),NOW+600000)
            def build(changed):
                return monitor._report('trip_end',start,end,[start,end],{'battery_capacity_kwh':86},False,
                                       decoder_changed=changed)
            ordinary=build(False)
            for index in range(5):
                report=self.historical();report['decoder_version']=ordinary['decoder_version']
                self.insert('good'+str(index),{'report_v2':report})
            self.assertTrue(compare(self.db,'car',ordinary)['available'])
            changed=build(True)
            self.assertFalse(compare(self.db,'car',changed)['available'])
            self.assertEqual(changed['metrics']['distance_km'],10)
            self.assertEqual(changed['metrics']['duration_seconds'],600)
            self.assertTrue(changed['quality']['decoder_changed_mid_session'])


    def test_deep_historical_json_is_excluded_without_losing_good_baseline(self):
        for index in range(5):self.insert('good'+str(index),{'report_v2':self.historical()})
        self.insert('deep',{})
        self.db.execute('UPDATE monitor_events SET summary=? WHERE id=?',
                        ('{"report_v2":'+'['*10000+'0'+']'*10000+'}','deep'))
        result=compare(self.db,'car',trip())
        self.assertTrue(result['available'])
        self.assertEqual(result['candidate_count'],5)
        self.assertEqual(result['excluded']['invalid_json'],1)

    def test_oversized_history_is_not_loaded_into_json_parser(self):
        from unittest.mock import patch
        from zeekr_control.usage_events import MAX_SUMMARY_BYTES
        for index in range(5):self.insert('good'+str(index),{'report_v2':self.historical()})
        self.insert('oversized',{})
        self.db.execute('UPDATE monitor_events SET summary=? WHERE id=?',('x'*(MAX_SUMMARY_BYTES+1),'oversized'))
        with patch('zeekr_control.report_history.json.loads',wraps=json.loads) as loads:
            result=compare(self.db,'car',trip())
        self.assertTrue(all(isinstance(call.args[0],str) and len(call.args[0].encode())<=MAX_SUMMARY_BYTES
                            for call in loads.call_args_list),'oversized history reached JSON parser')
        self.assertTrue(result['available'])
        self.assertEqual(result['candidate_count'],5)

    def test_history_limit_counts_utf8_bytes_and_accepts_exact_boundary(self):
        from unittest.mock import patch
        self.insert('one',{})
        encoded=json.dumps({'note':'测'*200},ensure_ascii=False)
        self.assertLess(len(encoded),512)
        self.db.execute('UPDATE monitor_events SET summary=?',(encoded,))
        with patch('zeekr_control.report_history.MAX_SUMMARY_BYTES',512),\
             patch('zeekr_control.report_history.json.loads',side_effect=AssertionError('oversized text decoded')):
            self.assertEqual(compare(self.db,'car',trip())['candidate_count'],0)
        encoded=json.dumps({'report_v2':self.historical()})
        encoded+=' '*(512-len(encoded.encode()))
        self.assertEqual(len(encoded.encode()),512)
        self.db.execute('UPDATE monitor_events SET summary=?',(encoded,))
        with patch('zeekr_control.report_history.MAX_SUMMARY_BYTES',512):
            self.assertEqual(compare(self.db,'car',trip())['candidate_count'],1)

    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE monitor_events(id TEXT,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
        self.db.execute('CREATE TABLE report_metric_index(event_id TEXT,vehicle TEXT,kind TEXT,end_time INTEGER,decoder_version TEXT,partial INTEGER,metrics TEXT)')

    def insert(self, identity, summary, kind='trip_end'):
        self.db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',
                        (identity,'car',kind,json.dumps(summary),NOW-1000))
        self.db.execute('INSERT INTO report_metric_index VALUES(?,?,?,?,?,?,?)',
                        (identity,'car',kind,NOW-1000,'we86-v1',0,'{}'))

    def historical(self):
        value=trip()
        value.update(start_time=NOW-700000,end_time=NOW-100000)
        return value

    def test_malformed_history_is_excluded_without_hiding_valid_baseline(self):
        for index in range(5):self.insert('good'+str(index),{'report_v2':self.historical()})
        bad=[[], {'report_v2':['invalid']}]
        for field in ('quality','metrics','profile_snapshot','start','end'):
            report=self.historical();report[field]=[]
            bad.append({'report_v2':report})
        for index, summary in enumerate(bad):self.insert('bad'+str(index),summary)
        result=compare(self.db,'car',trip())
        self.assertTrue(result['available'])
        self.assertEqual(result['candidate_count'],5)
        self.assertEqual(result['items'][0]['n'],5)
        self.assertEqual(sum(result['excluded'].values()),len(bad))
        self.assertEqual(self.db.execute('SELECT count(*) FROM monitor_events').fetchone()[0],12)

    def test_unknown_trip_duration_does_not_enter_pace_comparison(self):
        for value in (None, 'unknown', float('nan'), float('inf'), -1, 0, 10**400):
            with self.subTest(duration=value):
                current=trip();current['metrics']['duration_seconds']=value
                self.assertFalse(compare(self.db,'car',current)['available'])

    def test_unknown_charging_coverage_remains_unavailable(self):
        current=trip();current['kind']='charge_end'
        current.update(start={'soc':20},end={'soc':80})
        current['metrics']={'soc_delta':60,'duration_seconds':600,'charging_time_coverage':None,
                            'stop_detection_state_gap_seconds':None,'stop_detection_observed_gap_seconds':None}
        self.assertFalse(compare(self.db,'car',current)['available'])

    def test_nonfinite_history_metrics_never_form_a_baseline(self):
        for value in (None, 'unknown', float('inf'), float('nan'), -1, 0, 10**400):
            with self.subTest(duration=value):
                self.db.execute('DELETE FROM monitor_events')
                self.db.execute('DELETE FROM report_metric_index')
                for index in range(5):
                    report=self.historical();report['metrics']['duration_seconds']=value
                    self.insert(str(index),{'report_v2':report})
                self.assertFalse(compare(self.db,'car',trip())['available'])

    def test_damaged_history_cannot_block_a_new_trip_end_event(self):
        damaged=self.historical()
        damaged.update(decoder_version='we86-v2-ac',quality=[])
        self.assert_new_event_keeps_valid_baseline(json.dumps({'report_v2':damaged}))

    def test_deep_history_preserves_new_event_comparison(self):
        self.assert_new_event_keeps_valid_baseline('{"report_v2":'+'['*10000+'0'+']'*10000+'}')

    def test_oversized_history_preserves_new_event_comparison(self):
        from zeekr_control.usage_events import MAX_SUMMARY_BYTES
        self.assert_new_event_keeps_valid_baseline('x'*(MAX_SUMMARY_BYTES+1))

    def assert_new_event_keeps_valid_baseline(self,encoded):
        from zeekr_control.monitor import Monitor
        from test_monitor import sample
        with tempfile.TemporaryDirectory() as directory:
            monitor=Monitor(Path(directory)/'tracks.sqlite3')
            with monitor.tracks.connect() as db:
                for index in range(5):
                    report=self.historical();report['decoder_version']='we86-v2-ac'
                    identity='good'+str(index)
                    db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                               (identity,'car','trip_end',json.dumps({'report_v2':report}),'synthetic',NOW-1000))
                    db.execute('INSERT INTO report_metric_index VALUES(?,?,?,?,?,?,?)',
                               (identity,'car','trip_end',NOW-1000,'we86-v2-ac',0,'{}'))
                db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES('bad','car','trip_end',?,'synthetic',?)",(encoded,NOW-1000))
                db.execute("INSERT INTO report_metric_index VALUES('bad','car','trip_end',?,'we86-v2-ac',0,'{}')",(NOW-1000,))
            for second in (0,60,120):
                raw=sample(second, km=101 if second==60 else 110 if second==120 else 100,
                           speed=30 if second==60 else 0,
                           engine='engine_on' if second==60 else 'engine_off',ready=int(second==60))
                monitor.observe('car',raw,NOW+second*1000)
            for second in range(180,721,60):monitor.observe('car',sample(120,km=110),NOW+second*1000)
            with monitor.tracks.connect() as db:
                row=db.execute("SELECT summary FROM monitor_events WHERE kind='trip_end' AND created>=?",(NOW,)).fetchall()
                self.assertEqual(len(row),1)
                self.assertEqual(json.loads(row[0][0])['distance_km'],10)
                comparison=json.loads(row[0][0])['report_v2']['comparison']
                self.assertTrue(comparison['available'])
                self.assertEqual(comparison['candidate_count'],5)
                self.assertEqual(comparison['items'][0]['n'],5)
                self.assertEqual(db.execute("SELECT summary FROM monitor_events WHERE id='bad'").fetchone()[0],encoded)
