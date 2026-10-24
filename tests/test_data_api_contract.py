"""Cross-endpoint contracts, using synthetic accounts and temporary storage only."""
import json
import unittest
from unittest.mock import patch

import test_insights_api as fixtures
from zeekr_control.errors import RateLimited
from zeekr_control.monitor import Monitor
from zeekr_control.personal_store import account_scope
from zeekr_control.snapshots import session_scope
from zeekr_control.storage import save


class DataApiContractTests(unittest.TestCase):
    setUp = fixtures.InsightsApiTests.setUp
    cleanup_server = fixtures.InsightsApiTests.cleanup_server
    get = fixtures.InsightsApiTests.get
    post = fixtures.InsightsApiTests.post_ledger

    def add_trip(self):
        summary = dict(start_time=self.start+1000, end_time=self.start+61000,
                       duration_seconds=60, distance_km=12, partial=False)
        with Monitor(self.app.database_path).tracks.connect() as db:
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                       ('contract-trip', self.vehicle, 'trip_end', json.dumps(summary), '', summary['end_time']))

    def test_all_vehicle_reads_reject_replacement_account_without_its_snapshot(self):
        self.add_trip()
        save(self.path, {'accessToken':'SYNTHETIC-REPLACEMENT'})
        for route in ('/api/trips?date=2026-09-20', '/api/tracks?date=2026-09-20',
                      '/api/events?date=2026-09-20&kind=trip_end',
                      '/api/insights/report?period=month&date=2026-09-20'):
            status, body = self.get(route)
            self.assertEqual(status, 400, route)
            self.assertNotIn('contract-trip', json.dumps(body))

    def test_account_change_during_road_inference_discards_result(self):
        def replace(route):
            save(self.path, {'accessToken':'SYNTHETIC-REPLACEMENT'})
            return route
        with patch.object(self.app.road_matcher, 'enrich', side_effect=replace):
            self.assertEqual(self.get('/api/tracks?date=2026-09-20')[0], 409)

    def test_bill_revision_changes_without_changing_trip_revision(self):
        before = self.get('/api/state')[1]
        owner = account_scope(self.session)
        self.app.personal_store.change(owner, self.vehicle, 'charges', 'save', 'bill',
            dict(date='2026-09-20',actual_cents=1000,event=None), 0)
        after = self.get('/api/state')[1]
        self.assertEqual(before['trip_records_revision'], after['trip_records_revision'])
        self.assertNotEqual(before['personal_records_revision'], after['personal_records_revision'])

    def test_report_calendar_and_costs_share_payment_cutoff(self):
        owner = account_scope(self.session); scope = session_scope(self.session)
        now = self.start+12*3600000
        for revision, (date, cents) in enumerate((('2026-09-20',1000),('2026-09-25',2000))):
            self.app.personal_store.change(owner, self.vehicle, 'charges','save',str(revision),
                dict(date=date,actual_cents=cents,parking_fee_cents=0,event=None),revision)
        report = self.app.usage_reports.query(scope,self.vehicle,'month','2026-09-20',now,owner=owner)
        calendar = self.app.usage_calendar.query(scope,self.vehicle,'2026-09-20',now=now,owner=owner)
        costs = self.app.cost_summary.query(owner,self.vehicle,'2026-09-20',now=now)
        self.assertEqual([report['current']['totals']['charging_paid_cents'],
                          calendar['totals']['actual_cents'],costs['totals']['charge_cents']], [1000]*3)
        self.assertEqual(costs['future_record_count'],1)
        self.assertEqual(self.app.personal_store.read(owner,self.vehicle,'charges')['revision'],2)

    def test_conflicting_charge_modes_use_same_unknown(self):
        from zeekr_control.usage_events import project
        from zeekr_control.charging_analytics import _mode
        report = dict(start=dict(charging_mode='ac'),end=dict(charging_mode='dc'))
        event = project('mode','charge_end',dict(start_time=self.start,end_time=self.start+60000,report_v2=report))
        self.assertEqual(event['charge_mode'],_mode(report))
        self.assertEqual(event['charge_mode'],'unknown')

    def test_gateway_throttle_preserves_machine_retry_information(self):
        with patch.object(self.app,'recording',side_effect=RateLimited(120)):
            status,body = self.post({},route='/api/recording')
        self.assertEqual(status,429)
        self.assertEqual(body['code'],'gateway_rate_limited')
        self.assertEqual(body['retry_after_seconds'],120)
        self.assertTrue(body['retryable'])

    def test_all_json_routes_have_additive_metadata_and_errors_have_codes(self):
        for route in ('/api/state','/api/trips?date=2026-09-20','/api/vehicle/parameters',
                      '/api/insights/report?period=month&date=2026-09-20','/api/not-found'):
            status,body=self.get(route)
            self.assertEqual(body['meta']['schema_version'],1)
            self.assertEqual(body['meta']['timezone'],'Asia/Shanghai')
            self.assertEqual(body['meta']['units']['money'],'integer_cents')
            self.assertIsInstance(body['meta']['generated_at'],int)
            if status>=400:self.assertIsInstance(body['code'],str)

    def test_personal_revision_conflict_has_http_conflict_status(self):
        context=self.get('/api/state')[1]['insights_context']
        payload=dict(action='save',date='2026-09-20',source='public',amount='10',event_id='',context=context,revision=0)
        self.assertEqual(self.post(payload)[0],200)
        status,body=self.post(payload)
        self.assertEqual(status,409)
        self.assertEqual(body['code'],'data_changed')

    def test_event_end_totals_match_without_splitting_cross_midnight_distance(self):
        summary=dict(start_time=self.start-60000,end_time=self.start+60000,
                     duration_seconds=120,distance_km=12,partial=True)
        with Monitor(self.app.database_path).tracks.connect() as db:
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                ('overnight',self.vehicle,'trip_end',json.dumps(summary),'',summary['end_time']))
        report=self.app.insights('report','month','2026-09-20')
        calendar=self.app.insights('calendar','2026-09-20')
        day=self.app.insights('day-timeline','2026-09-20')
        self.assertEqual([report['current']['totals']['distance_km'],calendar['totals']['distance_km'],
                          day['summary']['distance_km']],[12]*3)
        earlier=calendar['days'][18];ended=calendar['days'][19]
        self.assertEqual((earlier['overlap_trip_count'],earlier['ended_trip_count']),(1,0))
        self.assertEqual((ended['overlap_trip_count'],ended['ended_trip_count']),(1,1))
        self.assertIsNone(earlier['distance_km'])
        self.assertEqual(report['current']['days'][19]['ended_trip_count'],1)

    def test_zero_payment_and_missing_payment_remain_distinct_across_summaries(self):
        owner=account_scope(self.session);scope=session_scope(self.session)
        for revision,(identity,amount) in enumerate((('missing',None),('free',0))):
            self.app.personal_store.change(owner,self.vehicle,'charges','save',identity,
                dict(date='2026-09-20',actual_cents=amount,parking_fee_cents=0,event=None),revision)
            values=[self.app.usage_reports.query(scope,self.vehicle,'month','2026-09-20',owner=owner)['current']['totals']['charging_paid_cents'],
                    self.app.usage_calendar.query(scope,self.vehicle,'2026-09-20',owner=owner)['totals']['actual_cents'],
                    self.app.cost_summary.query(owner,self.vehicle,'2026-09-20')['totals']['charge_cents']]
            self.assertEqual(values,[amount]*3)

    def test_sync_and_async_errors_share_codes_and_retry_policy(self):
        import time
        from zeekr_control.web import AnalysisBusy
        from zeekr_control.errors import RecordConflict
        for failure in (AnalysisBusy('busy'),RecordConflict('changed'),RateLimited(90)):
            with self.subTest(failure=type(failure).__name__),patch.object(self.app,'insights',side_effect=failure):
                status,body=self.get('/api/insights/report?period=month&date=2026-09-20')
                code,ticket=self.get('/api/insights/report?period=month&date=2026-09-20',{'Prefer':'respond-async'})
                self.assertEqual(code,202)
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    async_status,async_body=self.get(ticket['analysis_job_url'])
                    if async_status!=202:break
                    time.sleep(.01)
                self.assertEqual(async_status,status)
                self.assertEqual(async_body['code'],body['code'])
                self.assertEqual(async_body['retryable'],body['retryable'])
