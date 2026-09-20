"""Offline tests: identifiers and observations are synthetic, never owner records."""
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest

from zeekr_control.client import ApiError


class FakeClient:
    fail = False

    def __init__(self, session):
        pass

    def vehicles(self):
        return [{'vin': 'L6T79X2Z0NP000001'}, {'vin': 'L6T79X2Z0NP000002'}]

    def status(self, vin):
        if self.fail:
            raise ApiError('测试：会话失效')
        return {'updateTime': 1704067200000, 'accessToken': 'NEVER-EXPOSE',
                'position': {'latitude': 111600000, 'longitude': 435600000,
                             'posCanBeTrusted': True, 'marsCoordinates': False},
                'additionalVehicleStatus': {'electricVehicleStatus': {'chargeLevel': 62}}}


class WebServerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('zeekr_control.web'), 'Web 服务尚未实现')
        from zeekr_control.web import App, make_server
        from zeekr_control.storage import save
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        save(self.root / 'private' / 'session.json', {'accessToken': 'NEVER-EXPOSE', 'userId': 'private'})
        self.app = App(self.root / 'private' / 'session.json', self.root / 'private' / 'tracks.sqlite3', FakeClient)
        self.server = make_server(self.app, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:%d' % self.server.server_port
        self.key = self.request('GET', '/api/state')[1]['request_key']
        self.addCleanup(self.cleanup)

    def cleanup(self):
        FakeClient.fail = False
        self.app.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        data = json.dumps(body) if body is not None else None
        connection.request(method, path, data, headers or {})
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        connection.close()
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw.decode()

    def post(self, path, body):
        return self.request('POST', path, body, {'Origin': self.origin, 'Content-Type': 'application/json',
                                               'X-Request-Key': self.key})

    def test_refresh_redacts_identity_and_does_not_start_recording(self):
        code, data = self.post('/api/refresh', {'vehicle': 1})
        self.assertEqual(code, 200)
        self.assertEqual(data['model']['metrics']['battery'], '62%')
        self.assertTrue(data['recording']['active'])
        self.assertEqual(data['recording']['status'], 'offline')
        self.assertNotIn('NEVER-EXPOSE', str(data))
        self.assertNotIn('L6T79', str(data))
        self.assertNotIn('111600000', str(data))
        self.assertEqual(self.request('GET', '/api/location')[1]['latitude'], 31)

    def test_monitor_status_is_visible_without_exposing_webhook(self):
        from zeekr_control.storage import save
        save(self.root / 'private' / 'monitor-health.json',
             {'status': 'fresh', 'heartbeat': '1704067200000', 'trip': 'driving'})
        save(self.root / 'private' / 'wecom-webhook.json', {'webhook_url': 'SECRET-WEBHOOK'})
        code, data = self.request('GET', '/api/state')
        self.assertEqual(code, 200)
        self.assertEqual(data['monitoring']['status'], 'fresh')
        self.assertFalse(data['monitoring']['online'])
        self.assertNotIn('SECRET-WEBHOOK', json.dumps(data))

    def test_cross_origin_mutation_and_rebinding_are_rejected(self):
        self.assertEqual(self.request('POST', '/api/refresh', {}, {'Origin': 'https://evil.invalid',
            'Content-Type': 'application/json', 'X-Request-Key': self.key})[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Host': 'evil.invalid'})[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.request('POST', '/api/refresh', {})[0], 403)

    def test_failure_keeps_original_model_and_timestamp(self):
        original = self.post('/api/refresh', {'vehicle': 1})[1]
        FakeClient.fail = True
        self.assertEqual(self.post('/api/refresh', {'vehicle': 1})[0], 502)
        later = self.request('GET', '/api/state')[1]
        self.assertEqual(later['model'], original['model'])
        self.assertEqual(later['read_at'], original['read_at'])
        self.assertTrue(later['error'])

    def test_recording_controls_shared_backend_and_validates_interval(self):
        from zeekr_control.storage import load
        self.assertEqual(self.post('/api/recording', {'active': True, 'interval': 0})[0], 400)
        self.assertEqual(self.post('/api/recording', {'active': 'false', 'interval': 60})[0], 400)
        self.assertEqual(self.post('/api/recording', {'active': True, 'interval': 60})[0], 200)
        self.assertEqual(load(self.app.session_path.parent / 'sampling.json')['enabled'], 'true')
        self.assertEqual(self.post('/api/recording', {'active': False, 'interval': 60})[0], 200)
        self.assertEqual(load(self.app.session_path.parent / 'sampling.json')['enabled'], 'false')


    def test_history_unavailable_is_not_empty_success_and_bad_dates_fail(self):
        self.post('/api/refresh', {'vehicle': 1})
        data = self.request('GET', '/api/history?date=2024-01-01')[1]
        self.assertEqual(data['status'], 'authorization_required')
        self.assertNotIn('trips', data)
        self.assertEqual(self.request('GET', '/api/tracks?date=wrong')[0], 400)

    def test_static_traversal_and_unknown_api_not_served(self):
        self.assertEqual(self.request('GET', '/../../Myconfig.md')[0], 404)
        self.assertEqual(self.request('GET', '/api/unknown')[0], 404)

    def test_charging_process_returns_summary_and_series_together(self):
        self.post('/api/refresh', {'vehicle': 1})
        code, data = self.request('GET', '/api/charging/process?id=current&view=power-soc')
        self.assertEqual(code, 200)
        self.assertEqual(data['session']['status'], 'empty')
        self.assertEqual(data['series']['points'], [])

    def test_local_tracks_remain_readable_without_cloud_refresh_after_restart(self):
        from zeekr_control.web import App
        from zeekr_control.tracks import TrackStore
        TrackStore(self.app.database_path).record('synthetic', FakeClient({}).status('synthetic'), 1704067200000, 180)
        reopened = App(self.app.session_path, self.app.database_path, FakeClient)
        try:
            self.assertIsNone(reopened.model)
            self.assertEqual(len(reopened.state()['archived_vehicles']), 1)
            self.assertEqual(reopened.tracks('2024-01-01')['count'], 1)
        finally:
            reopened.close()

    def test_saved_background_snapshot_restores_without_gateway_query(self):
        from zeekr_control.snapshots import SnapshotStore, session_scope
        from zeekr_control.storage import load, save
        from zeekr_control.web import App
        vehicle_key = __import__('hashlib').sha256(b'L6T79X2Z0NP000001').hexdigest()
        save(self.app.session_path.parent / 'monitor-binding.json', {'vehicle_key': vehicle_key})
        SnapshotStore(self.app.session_path.parent / 'snapshots.sqlite3').publish(
            session_scope(load(self.app.session_path)), vehicle_key,
            FakeClient({}).status('synthetic'), 1704067201000)
        class NoGateway(FakeClient):
            def vehicles(self): raise AssertionError('GET /api/state must stay local')
            def status(self, vin): raise AssertionError('GET /api/state must stay local')
        reopened = App(self.app.session_path, self.app.database_path, NoGateway)
        try:
            result = reopened.state()
            self.assertEqual(result['model']['metrics']['battery'], '62%')
            self.assertEqual(result['snapshot_revision'], 1)
        finally:
            reopened.close()

    def test_events_endpoint_filters_current_vehicle_and_redacts_location(self):
        import json
        self.post('/api/refresh', {'vehicle': 1})
        from zeekr_control.monitor import Monitor
        monitor = Monitor(self.app.database_path)
        summary = {'start_time': 1704126500000, 'end_time': 1704126600000,
                   'duration_seconds': 100, 'distance_km': 2.5, 'partial': False,
                   'start_location': {'latitude': 31}, 'start_address': 'PRIVATE'}
        with monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                       ('event-a', self.app.vehicle_key, 'trip_end', json.dumps(summary), 'PRIVATE MESSAGE', 1))
            db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                       ('event-b', 'other', 'trip_end', json.dumps(summary), 'PRIVATE MESSAGE', 2))
        code, result = self.request('GET', '/api/events?date=2024-01-02&kind=trip_end')
        self.assertEqual(code, 200)
        self.assertEqual([event['id'] for event in result['events']], ['event-a'])
        self.assertNotIn('PRIVATE', str(result))

    def test_charging_analytics_routes_validate_and_stay_local(self):
        self.post('/api/refresh', {'vehicle': 1})
        self.assertEqual(self.request('GET', '/api/charging/session?id=current')[0], 200)
        self.assertEqual(self.request('GET', '/api/charging/series?id=current&view=wrong')[0], 400)
        code, result = self.request('GET', '/api/charging/statistics?days=30&mode=all')
        self.assertEqual(code, 200)
        self.assertEqual(result['summary']['ended_count'], 0)


    def test_background_failure_visible_in_shared_recording_state(self):
        import time
        from zeekr_control.storage import save
        self.post('/api/refresh', {'vehicle': 1})
        save(self.app.session_path.parent / 'monitor-health.json',
             {'status':'blocked', 'heartbeat':str(int(time.time()*1000)), 'error':'测试：会话失效'})
        result = self.app.state()
        self.assertEqual(result['recording']['status'], 'failed')
        self.assertEqual(result['recording']['error'], '采集后台异常，请检查服务状态。')
        self.assertEqual(result['model']['metrics']['battery'], '62%')


    def test_refresh_distinguishes_cache_unchanged_and_new_data(self):
        first = self.post('/api/refresh', {'vehicle': 1})[1]
        self.assertEqual(first.get('refresh_result'), 'new')
        second = self.post('/api/refresh', {'vehicle': 1})[1]
        self.assertEqual(second['refresh_result'], 'unchanged')
        from unittest.mock import patch
        with patch.object(FakeClient, 'last_query_cached', True, create=True):
            cached = self.post('/api/refresh', {'vehicle': 1})[1]
        self.assertEqual(cached['refresh_result'], 'cached')
        self.assertEqual(self.post('/api/refresh', {'vehicle': 2})[1]['refresh_result'], 'new')

    def test_recording_lifecycle_distinguishes_offline_paused_active(self):
        import time
        from zeekr_control.storage import save
        self.assertEqual(self.app.state()['recording']['status'], 'offline')
        save(self.app.session_path.parent / 'monitor-health.json',
             {'status':'fresh', 'heartbeat':str(int(time.time()*1000)), 'interval':'300'})
        self.assertEqual(self.app.state()['recording']['status'], 'active')
        self.assertEqual(self.app.state()['recording']['effective_interval'], 300)
        self.post('/api/recording', {'active': False, 'interval': 60})
        self.assertEqual(self.app.state()['recording']['status'], 'paused')


    def test_profiles_do_not_apply_same_car_to_multiple_vehicles(self):
        data = self.post('/api/refresh', {'vehicle': 2})[1]
        self.assertEqual(data.get('profile', {}).get('name'), '车辆 2')
        self.assertFalse(data['profile']['image'])

    def test_manual_refresh_failure_does_not_stop_shared_backend(self):
        from zeekr_control.storage import load
        self.post('/api/recording', {'active': True, 'interval': 60})
        FakeClient.fail = True
        self.assertEqual(self.post('/api/refresh', {'vehicle': 1})[0], 502)
        self.assertEqual(load(self.app.session_path.parent / 'sampling.json')['enabled'], 'true')


    def test_missing_and_older_vehicle_time_never_claim_new_data(self):
        from unittest.mock import patch
        self.post('/api/refresh', {'vehicle': 1})
        for timestamp, result in [(1704067191395, 'unchanged'), (None, 'time_unknown')]:
            with patch.object(FakeClient, 'status', return_value={'updateTime': timestamp}):
                self.assertEqual(self.post('/api/refresh', {'vehicle': 1})[1]['refresh_result'], result)

    def test_query_deadline_passes_through_success_and_failure(self):
        from unittest.mock import patch
        with patch.object(FakeClient, 'next_query_at', 2000000000, create=True):
            self.assertEqual(self.post('/api/refresh', {'vehicle': 1})[1]['next_query_at'], 2000000000)
            FakeClient.fail = True
            self.post('/api/refresh', {'vehicle': 1})
            self.assertEqual(self.app.state()['next_query_at'], 2000000000)

    def test_control_storage_failure_does_not_claim_success(self):
        from unittest.mock import patch
        self.post('/api/recording', {'active': False, 'interval': 60})
        with patch('zeekr_control.web.save', side_effect=OSError('disk unavailable')):
            self.assertEqual(self.post('/api/recording', {'active': True, 'interval': 60})[0], 500)
        self.assertFalse(self.app.state()['recording']['active'])
