"""Synthetic GW3 contracts; never contacts the owner's vehicle."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.errors import ApiError, RateLimited

LOWER = 1704038400000  # 2024-01-01 00:00 Asia/Shanghai
UPPER = 1704124800000
SESSION = {'userId': 'synthetic-user', 'accessToken': 'GW2-SECRET',
           'historyAccessToken': 'GW3-SECRET', 'historyDeviceId': 'test-device',
           'historyVin': base64.b64encode(b'x' * 32).decode(),
           'historyVehicleKey': hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest()}


def trip(**changes):
    value = {'tripId': 9223372036854770001, 'reportTime': LOWER + 7200000,
             'startTime': LOWER + 3600000, 'endTime': LOWER + 7200000,
             'traveledDistance': 42.5, 'avgSpeed': 42.5,
             'vin': 'PRIVATE-VIN', 'accessToken': 'PRIVATE-TOKEN'}
    return dict(value, **changes)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('zeekr_control.history'),
                             'Cloud history client is not implemented')
        from zeekr_control import history
        self.h = history
        self.calls = []
        self.response = {'code': '000000', 'success': True,
                         'data': {'data': [trip()], 'total': 1, 'lastId': LOWER + 7200000}}
        self.client = history.HistoryClient(SESSION, transport=self.transport)

    def transport(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        return self.response

    def test_beijing_day_and_time_cursor_not_page_number(self):
        result = self.client.day('2024-01-01')
        method, url, headers, body = self.calls[0]
        self.assertEqual(method, 'POST')
        self.assertEqual(url, 'https://snc-tsp-api.zeekrlife.com/ms-vehicle-trail/api/v1.0/journalLog/trip/listForPage')
        self.assertEqual(json.loads(body), {'startTime': LOWER, 'endTime': UPPER - 1,
                                          'pageSize': 20, 'currentPage': 1, 'lastId': -1})
        self.assertEqual(headers['Authorization'], 'Bearer GW3-SECRET')
        self.assertEqual(headers['X-VIN'], SESSION['historyVin'])
        self.assertNotIn('GW2-SECRET', str(headers))
        self.assertEqual(result['trips'][0]['id'], '9223372036854770001')
        self.assertEqual(result['trips'][0]['distance_km'], 42.5)
        self.assertEqual(result['trips'][0]['duration_minutes'], 60)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertIsNone(result['next_cursor'])
        self.response['data']['total'] = 35
        page = self.client.day('2024-01-01')
        self.assertEqual(page['next_cursor'], LOWER + 7200000 - 1)
        self.response['data'] = {'data': [], 'total': 0}
        self.client.day('2024-01-01', page['next_cursor'])
        self.assertEqual(json.loads(self.calls[-1][3])['startTime'], LOWER)
        self.assertEqual(json.loads(self.calls[-1][3])['endTime'], LOWER + 7200000 - 1)

    def test_invalid_inputs_never_send_request(self):
        for date in ('2024-1-1', '2024-02-30', '', '9999-12-31'):
            with self.assertRaises(ValueError):
                self.client.day(date)
        for cursor in (True, LOWER - 1, UPPER, 'oops', 1.5):
            with self.assertRaises(ValueError):
                self.client.day('2024-01-01', cursor)
        self.assertFalse(self.calls)

    def test_missing_credentials_not_empty_history(self):
        client = self.h.HistoryClient({'accessToken': 'GW2-SECRET'}, transport=self.transport)
        with self.assertRaises(self.h.HistoryError) as exc:
            client.day('2024-01-01')
        self.assertEqual(exc.exception.status, 'authorization_required')
        self.assertFalse(self.calls)

    def test_gateway_failures_never_become_empty_records_or_leak_body(self):
        for code, status in [('079001', 'forbidden'), ('079021', 'session_expired'),
                             ('401', 'session_expired'), ('079025', 'protocol_error'),
                             ('123456', 'request_failed')]:
            self.response = {'code': code, 'msg': 'PRIVATE-TOKEN PRIVATE-VIN', 'data': []}
            with self.assertRaises(self.h.HistoryError) as exc:
                self.client.day('2024-01-01')
            self.assertEqual(exc.exception.status, status)
            self.assertNotIn('PRIVATE', str(exc.exception))

    def test_malformed_success_and_stalled_cursor_are_errors(self):
        for data in (None, {}, {'total': 0}, {'data': None}, {'data': [None]},
                     {'data': [], 'total': 3}, {'data': [trip()], 'total': 35, 'lastId': UPPER + 1}):
            self.response = {'code': '000000', 'data': data}
            with self.assertRaises(self.h.HistoryError):
                self.client.day('2024-01-01')
        self.response = {'code': '000000', 'data': {'data': [], 'total': 0}}
        result = self.client.day('2024-01-01')
        self.assertEqual(result['status'], 'empty')
        self.assertEqual(result['trips'], [])

    def test_unknown_metrics_remain_unknown_and_midnight_trip_is_preserved(self):
        self.response['data']['data'] = [trip(startTime=LOWER - 600000,
            traveledDistance=None, avgSpeed=-1)]
        result = self.client.day('2024-01-01')['trips'][0]
        self.assertIsNone(result['distance_km'])
        self.assertIsNone(result['average_speed_kmh'])
        self.assertIn('2023-12-31', result['start_at'])

    def test_points_do_not_assume_coordinate_system_or_bridge_bad_points(self):
        self.response = {'code': '000000', 'data': {'trackPoints': [
            {'latitude': 31.0, 'longitude': 121.0, 'coordinateSystem': 'WGS84', 'reportTime': LOWER},
            {'latitude': 31.1, 'longitude': 121.1, 'coordinateSystem': 'WGS84', 'reportTime': LOWER + 60000},
            {'latitude': 0, 'longitude': 0, 'coordinateSystem': 'WGS84'},
            {'latitude': 31.2, 'longitude': 121.2, 'coordinateSystem': 'WGS84', 'reportTime': LOWER + 120000},
            {'latitude': 31.3, 'longitude': 121.3}]}}
        result = self.client.points('9223372036854770001', LOWER + 7200000)
        self.assertEqual([len(s) for s in result['segments']], [2, 1])
        self.assertEqual(result['count'], 5)
        self.assertFalse(result['points'][-1]['plottable'])
        self.assertIn('tripId=9223372036854770001', self.calls[-1][1])
        self.assertEqual(self.calls[-1][0], 'GET')
        self.response['data'] = {'trackPoints': []}
        self.assertEqual(self.client.points('1', LOWER)['status'], 'empty')
        self.response['data'] = {}
        with self.assertRaises(self.h.HistoryError):
            self.client.points('1', LOWER)

    def test_private_shared_cache_is_keyed_by_date_cursor_and_session(self):
        from zeekr_control.query_policy import QueryPolicy
        with tempfile.TemporaryDirectory() as directory:
            policy = QueryPolicy(Path(directory) / 'private' / 'queries.sqlite3')
            client = self.h.HistoryClient(SESSION, transport=self.transport, query_policy=policy)
            client.day('2024-01-01')
            client.day('2024-01-01')
            self.assertEqual(len(self.calls), 1)
            self.response['data'] = {'data': [], 'total': 0}
            client.day('2024-01-02')
            self.assertEqual(len(self.calls), 2)
            other = self.h.HistoryClient(dict(SESSION, historyAccessToken='other'),
                                         transport=self.transport, query_policy=policy)
            other.day('2024-01-02')
            self.assertEqual(len(self.calls), 3)

    def test_signature_matches_fixed_canonical_request(self):
        with patch('zeekr_control.history.time.time', return_value=1700000000), \
             patch('zeekr_control.history.uuid.uuid4', return_value='11111111-2222-3333-4444-555555555555'):
            self.client.day('2024-01-01')
        self.assertEqual(self.calls[0][2]['X-SIGNATURE'], 'Qdipep25G0TWnMb8JDJWw/V50it3d/oWhNepORUkOCM=')

    def test_http_auth_errors_keep_their_distinct_meaning(self):
        for code, expected in ((401, 'session_expired'), (403, 'forbidden'), (500, 'request_failed')):
            def fail(*args):
                raise ApiError('网关 HTTP %d；未自动重试。' % code, http_status=code)
            client = self.h.HistoryClient(SESSION, transport=fail)
            with self.assertRaises(self.h.HistoryError) as exc:
                client.day('2024-01-01')
            self.assertEqual(exc.exception.status, expected)

    def test_rate_limit_blocks_a_second_request_and_reports_remaining_wait(self):
        from zeekr_control.query_policy import QueryPolicy
        calls = []
        def fail(*args):
            calls.append(1)
            raise RateLimited(90)
        with tempfile.TemporaryDirectory() as directory:
            policy = QueryPolicy(Path(directory) / 'private' / 'queries.sqlite3', clock=lambda: 1700000000)
            client = self.h.HistoryClient(SESSION, transport=fail, query_policy=policy)
            with patch('zeekr_control.history.time.time', return_value=1700000000):
                for _ in range(2):
                    with self.assertRaises(self.h.HistoryError) as exc:
                        client.day('2024-01-01')
                    self.assertEqual(exc.exception.status, 'rate_limited')
                    self.assertEqual(exc.exception.retry_after, 90)
        self.assertEqual(calls, [1])

    def test_long_gaps_missing_times_and_truncation_never_join_a_route(self):
        self.response = {'code': '000000', 'data': {'coordinateSystem': 'WGS84', 'trackPoints': [
            {'latitude': 31, 'longitude': 121, 'reportTime': LOWER},
            {'latitude': 31.1, 'longitude': 121.1, 'reportTime': LOWER + 600000},
            {'latitude': 31.2, 'longitude': 121.2}]}}
        result = self.client.points('1', LOWER)
        self.assertEqual([len(segment) for segment in result['segments']], [1, 1, 1])
        self.response['data']['trackPoints'] = [{'latitude': 31, 'longitude': 121}] * 5001
        result = self.client.points('1', LOWER)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['count'], 5000)

    def test_import_validation_rejects_wrong_vin_and_header_injection(self):
        self.h.validate_session(SESSION)
        for change in ({'historyVin': 'L6T79X2Z0NP000001'},
                       {'historyAccessToken': 'token\r\nX-Bad: yes'},
                       {'historyDeviceId': ''}, {'historyVehicleKey': '../wrong'}):
            with self.assertRaises(self.h.HistoryError):
                self.h.validate_session(dict(SESSION, **change))


if __name__ == '__main__':
    unittest.main()
