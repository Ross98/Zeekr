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
        self.assertFalse(data['recording']['active'])
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

    def test_recording_requires_loaded_vehicle_and_valid_interval(self):
        self.assertEqual(self.post('/api/recording', {'active': True, 'interval': 300})[0], 400)
        self.post('/api/refresh', {'vehicle': 1})
        self.assertEqual(self.post('/api/recording', {'active': True, 'interval': 0})[0], 400)
        self.assertEqual(self.post('/api/recording', {'active': 'false', 'interval': 300})[0], 400)
        self.assertEqual(self.post('/api/recording', {'active': True, 'interval': 300})[0], 200)
        self.assertTrue(self.request('GET', '/api/state')[1]['recording']['active'])
        self.assertEqual(self.post('/api/refresh', {'vehicle': 2})[0], 400)
        self.assertEqual(self.post('/api/recording', {'active': False, 'interval': 300})[0], 200)

    def test_history_unavailable_is_not_empty_success_and_bad_dates_fail(self):
        self.post('/api/refresh', {'vehicle': 1})
        data = self.request('GET', '/api/history?date=2024-01-01')[1]
        self.assertEqual(data['status'], 'authorization_required')
        self.assertNotIn('trips', data)
        self.assertEqual(self.request('GET', '/api/tracks?date=wrong')[0], 400)

    def test_static_traversal_and_unknown_api_not_served(self):
        self.assertEqual(self.request('GET', '/../../Myconfig.md')[0], 404)
        self.assertEqual(self.request('GET', '/api/unknown')[0], 404)

    def test_local_tracks_remain_readable_without_cloud_refresh_after_restart(self):
        from zeekr_control.web import App
        self.post('/api/refresh', {'vehicle': 1})
        self.post('/api/recording', {'active': True, 'interval': 300})
        self.post('/api/recording', {'active': False, 'interval': 300})
        reopened = App(self.app.session_path, self.app.database_path, FakeClient)
        try:
            self.assertIsNone(reopened.model)
            self.assertEqual(len(reopened.state()['archived_vehicles']), 1)
            self.assertEqual(reopened.tracks('2024-01-01')['count'], 1)
        finally:
            reopened.close()

    def test_background_failure_pauses_collection(self):
        import time
        self.post('/api/refresh', {'vehicle': 1})
        self.post('/api/recording', {'active': True, 'interval': 300})
        FakeClient.fail = True
        with self.app.lock:
            self.app.next_due = 0
        deadline = time.monotonic() + 3
        while self.app.state()['recording']['active'] and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.app.state()['recording']['active'])
        self.assertEqual(self.app.state()['model']['metrics']['battery'], '62%')
        self.assertTrue(self.app.state()['error'])

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

    def test_recording_lifecycle_distinguishes_never_paused_failed(self):
        self.assertEqual(self.app.state()['recording'].get('status'), 'never')
        self.post('/api/refresh', {'vehicle': 1})
        self.post('/api/recording', {'active': True, 'interval': 300})
        self.assertEqual(self.app.state()['recording']['status'], 'active')
        self.post('/api/recording', {'active': False, 'interval': 300})
        self.assertEqual(self.app.state()['recording']['status'], 'paused')
        self.post('/api/recording', {'active': True, 'interval': 300})
        FakeClient.fail = True
        self.post('/api/refresh', {'vehicle': 1})
        self.assertEqual(self.app.state()['recording']['status'], 'failed')

    def test_profiles_do_not_apply_same_car_to_multiple_vehicles(self):
        data = self.post('/api/refresh', {'vehicle': 2})[1]
        self.assertEqual(data.get('profile', {}).get('name'), '车辆 2')
        self.assertFalse(data['profile']['image'])

    def test_storage_failure_marks_recording_failed(self):
        from unittest.mock import patch
        self.post('/api/refresh', {'vehicle': 1})
        self.post('/api/recording', {'active': True, 'interval': 300})
        with patch.object(self.app.store, 'record', side_effect=OSError('disk unavailable')):
            self.assertEqual(self.post('/api/refresh', {'vehicle': 1})[0], 500)
        self.assertFalse(self.app.state()['recording']['active'])
        self.assertEqual(self.app.state()['recording']['status'], 'failed')

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

    def test_initial_recording_storage_failure_reports_failed(self):
        from unittest.mock import patch
        self.post('/api/refresh', {'vehicle': 1})
        with patch.object(self.app, '_record', side_effect=OSError('disk unavailable')):
            self.assertEqual(self.post('/api/recording', {'active': True, 'interval': 300})[0], 500)
        self.assertEqual(self.app.state()['recording']['status'], 'failed')
        self.assertFalse(self.app.state()['recording']['active'])
