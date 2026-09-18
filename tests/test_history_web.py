"""History HTTP integration using the real parser and a synthetic transport."""
import unittest
import json
from unittest.mock import patch

import test_web_server as base
from test_history import SESSION, LOWER, trip
from zeekr_control.storage import save
from zeekr_control.history import HistoryClient


class HistoryWebTests(unittest.TestCase):
    cleanup = base.WebServerTests.cleanup
    request = base.WebServerTests.request
    post = base.WebServerTests.post
    def setUp(self):
        base.WebServerTests.setUp(self)
        self.responses = []
        self.calls = []
        def transport(method, url, headers, body):
            self.calls.append(url)
            return self.responses.pop(0)
        self.patch = patch('zeekr_control.web.HistoryClient',
                           side_effect=lambda session: HistoryClient(session, transport=transport), create=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def connect(self):
        save(self.app.session_path, SESSION)
        self.post('/api/refresh', {'vehicle': 1})

    def test_cloud_http_missing_auth_and_date_validation(self):
        self.post('/api/refresh', {'vehicle': 1})
        self.assertEqual(self.request('GET', '/api/history?date=2024-01-01')[1]['status'], 'authorization_required')
        self.assertEqual(self.request('GET', '/api/history?date=wrong')[0], 400)
        self.assertEqual(self.request('GET', '/api/history?date=2024-01-01&cursor=oops')[0], 400)
        self.assertEqual(len(self.calls), 0)

    def test_cloud_http_detail_only_for_listed_trip_and_current_vehicle(self):
        self.connect()
        self.responses.append({'code': '000000', 'data': {'data': [trip()], 'total': 1}})
        code, result = self.request('GET', '/api/history?date=2024-01-01')
        self.assertEqual(code, 200)
        self.assertEqual(result['status'], 'available')
        self.assertNotIn('GW3-SECRET', json.dumps(result))
        self.assertNotIn('PRIVATE', json.dumps(result))
        key = result['trips'][0]['key']
        self.assertEqual(self.request('GET', '/api/history/points?trip=made-up')[0], 400)
        self.responses.append({'code': '000000', 'data': {'trackPoints': []}})
        self.assertEqual(self.request('GET', '/api/history/points?trip=' + key)[1]['status'], 'empty')
        self.post('/api/refresh', {'vehicle': 2})
        self.assertEqual(self.request('GET', '/api/history/points?trip=' + key)[0], 400)
        self.assertEqual(len(self.calls), 2)

    def test_cloud_http_failure_does_not_pause_recording_or_discard_state(self):
        self.connect()
        self.post('/api/recording', {'active': True, 'interval': 60})
        self.responses.append({'code': '079001', 'msg': 'PRIVATE'})
        result = self.request('GET', '/api/history?date=2024-01-01')[1]
        self.assertEqual(result['status'], 'forbidden')
        self.assertNotIn('trips', result)
        self.assertTrue(self.app.state()['recording']['active'])
        self.assertIsNotNone(self.app.state()['model'])

    def test_cloud_old_detail_cannot_be_reused_after_credentials_change(self):
        self.connect()
        self.responses.append({'code': '000000', 'data': {'data': [trip()], 'total': 1}})
        result = self.request('GET', '/api/history?date=2024-01-01')[1]
        self.assertEqual(result['status'], 'available')
        key = result['trips'][0]['key']
        save(self.app.session_path, dict(SESSION, historyAccessToken='different-session'))
        self.assertEqual(self.request('GET', '/api/history/points?trip=' + key)[0], 400)
        self.assertEqual(len(self.calls), 1)

    # The existing no-credentials contract now has a concrete actionable state.
    def test_history_unavailable_is_not_empty_success_and_bad_dates_fail(self):
        self.post('/api/refresh', {'vehicle': 1})
        data = self.request('GET', '/api/history?date=2024-01-01')[1]
        self.assertEqual(data['status'], 'authorization_required')
        self.assertNotIn('trips', data)
