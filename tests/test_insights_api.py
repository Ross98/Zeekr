import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from zeekr_control.storage import save
from zeekr_control.snapshots import session_scope
from zeekr_control.tracks import day_bounds
from zeekr_control.web import App, make_server
from zeekr_control.personal_store import account_scope
from zeekr_control.parking_analytics import ParkingAnalytics


class InsightsApiTests(unittest.TestCase):
    def test_tyre_settings_require_context_revision_and_request_key(self):
        code,result=self.get('/api/insights/tyres')
        self.assertEqual(code,200)
        self.assertEqual(result['config'],dict(enabled=True,load='light',revision=0))
        payload=dict(context=result['context'],action='save',revision=0,enabled=True,load='full')
        self.assertEqual(self.post_ledger(payload,{'X-Request-Key':''},'/api/insights/tyres')[0],403)
        self.assertEqual(self.post_ledger(dict(payload,context='old'),route='/api/insights/tyres')[0],400)
        code,result=self.post_ledger(payload,route='/api/insights/tyres')
        self.assertEqual(code,200);self.assertEqual(result['base'],290)
        self.assertEqual(result['config']['revision'],1)
        self.assertEqual(self.post_ledger(payload,route='/api/insights/tyres')[0],400)
        self.assertEqual(self.get('/api/insights/tyres')[1]['config']['load'],'full')

    def test_travel_tools_api_validation_and_assets(self):
        for path in ('/api/insights/routes?date=2026-09-20','/api/insights/review?date=2026-09-20','/travel-insights.js','/navigation-state.js'):
            self.assertEqual(self.get(path)[0],200)
        self.assertEqual(self.get('/api/insights/routes?date=invalid')[0],400)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'private' / 'session.json'
        self.session = {'accessToken': 'SYNTHETIC-SECRET'}
        save(self.path, self.session)
        self.app = App(self.path, client_factory=lambda _: self.fail('No cloud access permitted'))
        self.app._sync_session(self.session)
        self.app.profile = {'name': '合成车辆', 'battery_capacity_kwh': 86}
        self.addCleanup(self.app.close)
        self.vehicle = hashlib.sha256(b'SYNTHETIC-CAR').hexdigest()
        save(self.path.parent / 'monitor-binding.json', {'vehicle_key': self.vehicle})
        self.start, _ = day_bounds('2026-09-20')
        for offset, soc in [(0, 70), (60000, 69)]:
            self.app.snapshot_store.publish(session_scope(self.session), self.vehicle,
                {'updateTime': self.start + offset, 'vin': 'PRIVATE-VIN',
                 'additionalVehicleStatus': {'electricVehicleStatus': {'chargeLevel': soc}}},
                self.start + offset, source='monitor')
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup_server)

    def cleanup_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def get(self, route, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request('GET', route, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        status = response.status
        connection.close()
        try:
            body = json.loads(body)
        except ValueError:
            pass
        return status, body

    def test_event_route_passes_inclusive_charge_range(self):
        from zeekr_control.monitor import Monitor
        monitor = Monitor(self.app.event_store.path)
        for name, stamp in [('first', self.start), ('last', self.start + 2*86400000 - 1),
                            ('outside', self.start + 2*86400000)]:
            with monitor.tracks.connect() as db:
                db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                           (name, self.vehicle, 'charge_end', json.dumps({'end_time': stamp}), '', stamp))
        code, result = self.get('/api/events?date=2026-09-20&end=2026-09-21&kind=charge_end')
        self.assertEqual(code, 200)
        self.assertEqual([row['id'] for row in result['events']], ['last', 'first'])
        code, result = self.get('/api/events?date=2026-09-20&kind=charge_end')
        self.assertEqual(code, 200)
        self.assertEqual([row['id'] for row in result['events']], ['first'])

    def test_full_readonly_flow_context_and_assets(self):
        state = self.get('/api/state')[1]
        code, page = self.get('/api/insights/timeline?date=2026-09-20')
        self.assertEqual(code, 200)
        self.assertEqual(len(page['items']), 2)
        self.assertEqual(page['context'], state['insights_context'])
        keys = [r['key'] for r in page['items']]
        code, detail = self.get('/api/insights/snapshot?id=' + keys[0])
        self.assertEqual(code, 200)
        self.assertEqual(detail['summary']['battery'], '70%')
        code, comparison = self.get('/api/insights/compare?before=%s&after=%s' % tuple(keys))
        self.assertEqual(code, 200)
        self.assertTrue(comparison['changes'])
        for secret in ('PRIVATE-VIN', 'SYNTHETIC-SECRET', session_scope(self.session)):
            self.assertNotIn(secret, json.dumps([state, page, detail, comparison]))
        for route in ('/insights.js', '/insights.css'):
            self.assertEqual(self.get(route)[0], 200)

    def test_bad_parameters_and_origin(self):
        for route in ('/api/insights/timeline?date=', '/api/insights/snapshot?id=../../session.json',
                      '/api/insights/compare?before=202609.1&after=202609.999'):
            self.assertEqual(self.get(route)[0], 400)
        self.assertEqual(self.get('/api/insights/timeline?date=2026-09-20',
                                 {'Origin': 'https://untrusted.example'})[0], 403)

    def test_parking_is_scoped_and_rejects_unbounded_ranges(self):
        code, result = self.get('/api/insights/parking?start=2026-09-20&end=2026-09-20')
        self.assertEqual(code, 200)
        self.assertEqual(result['quality']['read_count'], 2)
        self.assertEqual(result['sessions'], [])
        self.assertTrue(result['context'])
        for query in ('start=2026-09-20&end=2026-09-19', 'start=2026-01-01&end=2026-09-20', 'start=&end='):
            self.assertEqual(self.get('/api/insights/parking?' + query)[0], 400)

    def test_state_remains_responsive_during_parking_analysis(self):
        entered, release, completed = threading.Event(), threading.Event(), threading.Event()
        parking_result, state_result = [], []
        def slow_query(*args):
            entered.set()
            release.wait(3)
            return {'events': [], 'calculation_version': 2}
        def parking_request():
            parking_result.append(self.get('/api/insights/parking?start=2026-09-20&end=2026-09-20')[0])
        def state_request():
            state_result.append(self.get('/api/state')[0])
            completed.set()
        with patch.object(ParkingAnalytics, 'query', side_effect=slow_query):
            worker = threading.Thread(target=parking_request)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                state_worker = threading.Thread(target=state_request)
                state_worker.start()
                responsive = completed.wait(.5)
            finally:
                release.set()
                worker.join(3)
                state_worker.join(3)
        self.assertTrue(responsive, 'parking analysis must not block /api/state')
        self.assertEqual(parking_result, [200])
        self.assertEqual(state_result, [200])

    def test_parking_rejects_account_change_during_analysis(self):
        def changed_query(*args):
            save(self.path, {'accessToken': 'DIFFERENT-OWNER'})
            return {'events': [], 'calculation_version': 2}
        with patch.object(ParkingAnalytics, 'query', side_effect=changed_query):
            self.assertEqual(self.get('/api/insights/parking?start=2026-09-20&end=2026-09-20')[0], 400)

    def test_automatic_insights_reads_cache_only_and_rejects_switched_account(self):
        route = '/api/insights/automatic'
        status, data = self.get(route)
        self.assertEqual(status, 200)
        self.assertEqual(data['status'], 'waiting')
        self.assertFalse(self.app.automatic_cache.path.exists())
        report = self.app.automatic_analyzer.build(session_scope(self.session), self.vehicle, self.start+60000)
        self.app.automatic_cache.success(session_scope(self.session), self.vehicle, self.start+60000, report)
        with patch.object(self.app.automatic_analyzer, 'build', side_effect=AssertionError('GET must not analyze')):
            self.assertEqual(self.get(route)[1]['report']['quality']['reads'], 2)
        original = self.app.automatic_cache.query
        def switched(*args):
            result = original(*args)
            save(self.path, {'accessToken': 'DIFFERENT-OWNER'})
            return result
        with patch.object(self.app.automatic_cache, 'query', side_effect=switched):
            self.assertEqual(self.get(route)[0], 400)
        self.assertNotIn('report', self.get(route)[1])

    def test_automatic_analysis_and_script_require_auth(self):
        from zeekr_control.auth import WebAuth, password_record
        protected = make_server(self.app, 0, auth=WebAuth(password_record('synthetic-password')))
        thread = threading.Thread(target=protected.serve_forever, daemon=True); thread.start()
        try:
            for path in ('/api/insights/automatic', '/automatic-insights.js','/api/insights/routes?date=2026-09-20','/api/insights/review?date=2026-09-20','/travel-insights.js','/navigation-state.js'):
                conn = http.client.HTTPConnection('127.0.0.1', protected.server_port)
                conn.request('GET', path); response = conn.getresponse()
                self.assertEqual(response.status, 401); response.read(); conn.close()
        finally:
            protected.shutdown(); protected.server_close(); thread.join()

    def test_period_report_has_scope_and_validates_period(self):
        code, data = self.get('/api/insights/report?period=month&date=2026-09-20')
        self.assertEqual(code, 200)
        self.assertEqual(data['current']['window']['start_date'], '2026-09-01')
        self.assertEqual(data['current']['coverage']['days_with_reads'], 1)
        self.assertEqual(data['context'], self.get('/api/state')[1]['insights_context'])
        self.assertEqual(self.get('/api/insights/report?period=year&date=2026-09-20')[0], 400)

    def test_session_change_rejects_old_selected_records(self):
        first = self.get('/api/insights/timeline?date=2026-09-20')[1]
        save(self.path, {'accessToken': 'DIFFERENT-OWNER'})
        self.assertEqual(self.get('/api/insights/snapshot?id=' + first['items'][0]['key'])[0], 400)
        second = self.get('/api/insights/timeline?date=2026-09-20')[1]
        self.assertEqual(second['items'], [])
        self.assertNotEqual(first['context'], second['context'])

    def test_session_change_during_read_discards_response(self):
        original = self.app.archive_reader.timeline
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            save(self.path, {'accessToken': 'DIFFERENT-OWNER'})
            return result
        with patch.object(self.app.archive_reader, 'timeline', side_effect=changed):
            self.assertEqual(self.get('/api/insights/timeline?date=2026-09-20')[0], 400)

    def test_account_change_without_latest_snapshot_discards_archive_response(self):
        original=self.app.archive_reader.timeline
        def changed(*args,**kwargs):
            result=original(*args,**kwargs)
            self.assertEqual(len(result['items']),2)
            self.assertIsNone(self.app._insights_context())
            save(self.path,{'accessToken':'DIFFERENT-OWNER'})
            return result
        # Older archives can exist after the latest-snapshot cache was removed.
        # Both accounts then have a null UI context; scope must still be checked.
        with patch.object(self.app.snapshot_store,'read',return_value=None),patch.object(self.app.archive_reader,'timeline',side_effect=changed):
            status,body=self.get('/api/insights/timeline?date=2026-09-20')
        self.assertEqual(status,400)
        self.assertNotIn('items',body)

    def post_ledger(self,data,headers=None,route='/api/insights/ledger'):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        h={'Content-Type':'application/json','Origin':'http://127.0.0.1:%d'%self.server.server_port,
           'X-Request-Key':self.app.request_key}
        h.update(headers or {})
        c.request('POST',route,json.dumps(data),h)
        response=c.getresponse();status=response.status;body=json.loads(response.read());c.close()
        return status,body

    def test_ledger_write_requires_origin_context_revision_and_survives_reopen(self):
        context=self.get('/api/state')[1]['insights_context']
        payload={'context':context,'action':'save','revision':0,'event_id':'','date':'2026-09-20',
                 'source':'home','amount':'12.34','note':'<script>synthetic</script>'}
        self.assertEqual(self.post_ledger(payload,{'X-Request-Key':''})[0],403)
        self.assertEqual(self.post_ledger(dict(payload,context='old-context'))[0],400)
        code,saved=self.post_ledger(payload)
        self.assertEqual(code,200)
        self.assertEqual(saved['revision'],1)
        self.assertEqual(self.post_ledger(payload)[0],400)
        data=self.get('/api/insights/ledger?date=2026-09-20')[1]
        self.assertEqual(data['totals']['actual_cents'],1234)
        reopened=App(self.path)
        try:
            self.assertEqual(reopened.insights('ledger','2026-09-20')['totals']['actual_cents'],1234)
        finally:reopened.close()

    def test_account_switch_before_commit_rolls_back_ledger(self):
        context=self.get('/api/state')[1]['insights_context']
        original=self.app.personal_store.change
        def switched(*args,**kwargs):
            real_guard=kwargs['guard']
            def guard():
                save(self.path,{'accessToken':'NEW-ACCOUNT'})
                real_guard()
            kwargs['guard']=guard
            return original(*args,**kwargs)
        with patch.object(self.app.personal_store,'change',side_effect=switched):
            code,_=self.post_ledger({'context':context,'action':'save','revision':0,'event_id':'',
                                    'date':'2026-09-20','source':'home','amount':'99'})
        self.assertEqual(code,400)
        self.assertEqual(self.app.personal_store.read(account_scope(self.session),self.vehicle,'charges')['revision'],0)

    def test_rule_create_preview_and_account_scope(self):
        payload=dict(context=self.get('/api/state')[1]['insights_context'],action='save',revision=0,
                     name='合成低电量',kind='low_soc',threshold=80,enabled=True,
                     confirm_seconds=60,cooldown_minutes=60,delivery='in_app',recovery=True)
        self.assertEqual(self.post_ledger(payload,{'X-Request-Key':''},'/api/insights/rules')[0],403)
        code,result=self.post_ledger(payload,route='/api/insights/rules/preview')
        self.assertEqual(code,200)
        self.assertIn('matches',result)
        self.assertFalse(self.app.personal_store.path.exists())
        self.assertEqual(self.post_ledger(payload,route='/api/insights/rules')[0],200)
        code,result=self.get('/api/insights/rules')
        self.assertEqual(code,200);self.assertEqual(len(result['records']),1)
        self.assertEqual(result['history'],[])
        save(self.path,{'accessToken':'OTHER-ACCOUNT'})
        self.assertEqual(self.get('/api/insights/rules')[0],400)
        self.assertEqual(self.post_ledger(payload,route='/api/insights/rules')[0],400)

    def test_trip_tags_roundtrip_delete_restore_and_scope(self):
        from zeekr_control.monitor import Monitor
        with Monitor(self.app.database_path).tracks.connect() as db:
            event=dict(start_time=self.start,end_time=self.start+3600000,duration_seconds=3600,
                distance_km=40,start_soc=70,end_soc=60,soc_delta=-10,partial=False,battery_capacity_kwh=86)
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                ('tag-trip',self.vehicle,'trip_end',json.dumps(event),'private-message',self.start))
        context=self.get('/api/state')[1]['insights_context']
        payload=dict(context=context,action='save',revision=0,event_id='tag-trip',tags=['通勤','接娃'],note='合成备注')
        code,saved=self.post_ledger(payload,route='/api/insights/trip-tags')
        self.assertEqual(code,200)
        result=self.get('/api/insights/trip-tags?date=2026-09-20')[1]
        self.assertEqual(result['groups'][0]['complete_count'],1)
        self.assertNotIn('private-message',json.dumps(result))
        self.assertEqual(self.post_ledger(dict(context=context,action='delete',id=saved['id'],revision=1),route='/api/insights/trip-tags')[0],200)
        self.assertEqual(self.get('/api/insights/trip-tags?date=2026-09-20')[1]['groups'],[])
        self.assertEqual(self.post_ledger(dict(context=context,action='restore',id=saved['id'],revision=2),route='/api/insights/trip-tags')[0],200)
        save(self.path,{'accessToken':'OTHER-OWNER'})
        self.assertEqual(self.get('/api/insights/trip-tags?date=2026-09-20')[0],400)

    def test_commute_rule_write_requires_current_context_and_is_private(self):
        context=self.get('/api/state')[1]['insights_context']
        payload=dict(context=context,action='commute-save',revision=0,
                     home=dict(latitude=31.2,longitude=121.4,radius_m=300),
                     work=dict(latitude=31.21,longitude=121.41,radius_m=500))
        self.assertEqual(self.post_ledger(payload,{'X-Request-Key':''},'/api/insights/trip-tags')[0],403)
        self.assertEqual(self.post_ledger(dict(payload,context='old'),route='/api/insights/trip-tags')[0],400)
        self.assertEqual(self.post_ledger(payload,route='/api/insights/trip-tags')[0],200)
        rule=self.get('/api/insights/trip-tags?date=2026-09-20')[1]['commute_rule']
        self.assertEqual(rule['home']['radius_m'],300)
        self.assertEqual(rule['work']['radius_m'],500)
        self.assertEqual(self.post_ledger(payload,route='/api/insights/trip-tags')[0],400)
        save(self.path,{'accessToken':'OTHER-ACCOUNT'})
        self.assertEqual(self.get('/api/insights/trip-tags?date=2026-09-20')[0],400)

    def test_previous_binding_without_current_account_snapshot_cannot_read_vehicle_events(self):
        save(self.path,{'accessToken':'OTHER-ACCOUNT'})
        self.assertIsNone(self.get('/api/state')[1]['insights_context'])
        for route in ('report?period=month&date=2026-09-20','ledger?date=2026-09-20',
                      'rules','trip-tags?date=2026-09-20','charge-comparison/options?date=2026-07-12',
                      'charge-comparison?a=curve-a&b=curve-b','experiments','experiments/detail?id=missing',
                      'calendar?date=2026-09-20','life?date=2026-09-20','quality?start=2026-09-20&end=2026-09-20'):
            self.assertEqual(self.get('/api/insights/'+route)[0],400,route)

    def test_charging_comparison_projection_and_account_context(self):
        from test_charge_comparison import add_curve,curve_point
        for identity,offset,mode in (('curve-a',0,'dc'),('curve-b',86400000,'ac')):
            add_curve(self.app.database_path,identity,self.vehicle,
                [curve_point(self.start+offset+i*60000,soc,7 if mode=='ac' else 100,mode) for i,soc in enumerate((30,40,50,60))])
        code,result=self.get('/api/insights/charge-comparison?a=curve-a&b=curve-b')
        self.assertEqual(code,200);self.assertEqual(result['common']['low'],30)
        self.assertNotIn('NEVER-EXPORT',json.dumps(result))
        self.assertEqual(result['context'],self.get('/api/state')[1]['insights_context'])
        self.assertEqual(self.get('/api/insights/charge-comparison?a=curve-a&b=curve-a')[0],400)
        self.assertEqual(len(self.get('/api/insights/charge-comparison/options?date=2026-09-20')[1]['events']),2)

    def test_parameter_experiment_freezes_safe_comparison_without_field_review_write(self):
        timeline=self.get('/api/insights/timeline?date=2026-09-20')[1]
        before,after=[row['key'] for row in timeline['items']]
        payload=dict(context=timeline['context'],action='save',revision=0,title='合成实验',action_text='用户记录动作',
            action_at=self.start+30000,before=before,after=after,note='线索待核验',
            paths=['additionalVehicleStatus.electricVehicleStatus.chargeLevel'])
        code,saved=self.post_ledger(payload,route='/api/insights/experiments')
        self.assertEqual(code,200)
        summary=self.get('/api/insights/experiments')[1]['records'][0]
        self.assertEqual(summary['body']['change_count'],1)
        detail=self.get('/api/insights/experiments/detail?id='+saved['id'])[1]
        self.assertEqual(detail['body']['status'],'research_only')
        self.assertNotIn('PRIVATE-VIN',json.dumps(detail))
        self.assertFalse(self.app.field_review_store.path.exists())
        self.assertEqual(self.post_ledger(payload,route='/api/insights/experiments')[0],400)

    def test_calendar_is_readonly_private_and_has_beijing_month_days(self):
        code,result=self.get('/api/insights/calendar?date=2026-09-20')
        self.assertEqual(code,200)
        self.assertEqual(len(result['days']),30)
        self.assertEqual(result['days'][19]['reads'],2)
        self.assertEqual(result['context'],self.get('/api/state')[1]['insights_context'])
        self.assertNotIn('PRIVATE-VIN',json.dumps(result))
        self.assertFalse(self.app.personal_store.path.exists())
        self.assertEqual(self.get('/api/insights/calendar?date=bad')[0],400)
        self.assertEqual(self.get('/usage-calendar.js')[0],200)

    def test_life_expenses_and_reminders_have_separate_revisions_and_no_cloud(self):
        code,result=self.get('/api/insights/life?date=2026-09-20')
        self.assertEqual(code,200);self.assertFalse(self.app.personal_store.path.exists())
        context=result['context']
        expense=dict(collection='expenses',action='save',revision=0,context=context,
                     date='2026-09-20',category='洗车',title='合成洗车',amount='30.10')
        self.assertEqual(self.post_ledger(expense,route='/api/insights/life')[0],200)
        reminder=dict(collection='reminders',action='save',revision=0,context=context,
                      title='合成保养',due_date='2026-09-20')
        code,saved=self.post_ledger(reminder,route='/api/insights/life')
        self.assertEqual(code,200)
        result=self.get('/api/insights/life?date=2026-09-20')[1]
        self.assertEqual(result['expenses']['total_cents'],3010)
        self.assertEqual(result['reminders']['revision'],1)
        ranged=self.get('/api/insights/life?start=2026-08-01&end=2026-09-20')[1]
        self.assertEqual(ranged['expenses']['total_cents'],3010)
        self.assertEqual(ranged['window']['start_date'],'2026-08-01')
        self.assertEqual(self.get('/api/insights/life?start=2026-09-21&end=2026-09-20')[0],400)
        self.assertNotIn('PRIVATE-VIN',json.dumps(result))
        self.assertEqual(self.get('/vehicle-life.js')[0],200)
        invalid=dict(reminder,collection='rules')
        self.assertEqual(self.post_ledger(invalid,route='/api/insights/life')[0],400)

    def test_data_quality_only_projects_scoped_timing_metadata(self):
        code,result=self.get('/api/insights/quality?start=2026-09-20&end=2026-09-20')
        self.assertEqual(code,200);self.assertEqual(result['reads'],2)
        self.assertEqual(result['counts']['new'],2)
        self.assertNotIn('PRIVATE-VIN',json.dumps(result))
        self.assertEqual(self.get('/data-quality.js')[0],200)
        self.assertEqual(self.get('/api/insights/quality?start=2026-01-01&end=2026-09-20')[0],400)

    def test_trip_cards_removed(self):
        for route in ('/api/insights/cards?date=2026-09-20', '/trip-cards.js', '/trip-card-renderer.js'):
            self.assertEqual(self.get(route)[0], 404)


if __name__ == '__main__':
    unittest.main()
