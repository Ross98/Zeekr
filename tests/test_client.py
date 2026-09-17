"""Offline tests: identifiers and observations are synthetic, never owner records."""
import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from zeekr_control.client import Client, ApiError, GW2_SECRET


class Transport:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        return self.replies.pop(0)


def ok(data):
    return {'code': '000000', 'data': data}


class ClientTests(unittest.TestCase):
    def test_jwt_exchange_then_read_shared_vehicles(self):
        wire = Transport(ok({'YIKAT_NEW': 'code'}), ok({
            'accessToken': 'access', 'userId': 'user', 'clientId': 'client'}),
            {'code': '1000', 'data': {'list': [{'vin': 'L1234567890123456'}]}})
        client = Client(transport=wire)
        client.login_jwt('test-jwt')
        self.assertEqual(client.vehicles(), [{'vin': 'L1234567890123456'}])
        self.assertIn('needSharedCar=1', wire.calls[2][1])
        self.assertEqual(wire.calls[2][2]['authorization'], 'access')
        self.assertEqual(wire.calls[1][3], b'{"authCode":"code"}')

    def test_signature_covers_exact_post_bytes(self):
        wire = Transport(ok({'accessToken': 'token', 'userId': 'uid', 'clientId': 'cid'}))
        client = Client(transport=wire)
        with patch('zeekr_control.client.timestamp', return_value='1700000000000'), \
             patch('zeekr_control.client.nonce', return_value='FIXED'):
            client._request('line_login', payload={'authCode': '中文'})
        method, url, headers, body = wire.calls[0]
        self.assertEqual(body, '{"authCode":"中文"}'.encode())
        digest = base64.b64encode(hashlib.md5(body).digest()).decode()
        canonical = ('application/json;responseformat=3\nx-api-signature-nonce:FIXED\n'
                     'x-api-signature-version:1.0\n\nidentity_type=zeekr\n' + digest +
                     '\n1700000000000\nPOST\n/auth/account/session/secure')
        expected = base64.b64encode(hmac.new(GW2_SECRET.encode(), canonical.encode(), hashlib.sha1).digest()).decode()
        self.assertEqual(headers['x-signature'], expected)

    def test_status_query_not_double_encoded(self):
        wire = Transport(ok({'vehicleStatus': {'soc': 0}}))
        client = Client({'accessToken': 'a', 'userId': 'u', 'clientId': 'c'}, wire)
        self.assertEqual(client.status('L1234567890123456'), {'soc': 0})
        self.assertIn('target=basic%2Cmore', wire.calls[0][1])
        self.assertNotIn('%252C', wire.calls[0][1])
        self.assertIn('latest=Local', wire.calls[0][1])

    def test_invalid_vin_never_reaches_network(self):
        wire = Transport()
        client = Client({'accessToken': 'a', 'userId': 'u'}, wire)
        for vin in ('../unlock', 'short', 'L1234567890123456I'):
            with self.assertRaises(ApiError):
                client.status(vin)
        self.assertEqual(wire.calls, [])

    def test_business_failure_redacts_server_message(self):
        wire = Transport({'code': '079021', 'msg': 'secret-token phone VIN'})
        client = Client({'accessToken': 'a', 'userId': 'u'}, wire)
        with self.assertRaises(ApiError) as raised:
            client.vehicles()
        self.assertIn('079021', str(raised.exception))
        self.assertNotIn('secret-token', str(raised.exception))

    def test_malformed_success_not_empty_vehicle_list(self):
        for response in ([], {}, ok({}), ok({'list': 'bad'}), ok({'list': [5]})):
            client = Client({'accessToken': 'a', 'userId': 'u'}, Transport(response))
            with self.assertRaises(ApiError):
                client.vehicles()

    def test_missing_user_id_rejects_login(self):
        client = Client(transport=Transport(ok({'YIKAT_NEW': 'c'}), ok({'accessToken': 'a'})))
        with self.assertRaises(ApiError):
            client.login_jwt('jwt')

    def test_sms_phone_and_region_encoded(self):
        wire = Transport(ok({}))
        client = Client(transport=wire)
        client.send_sms('13800000000')
        self.assertIn('regionCode=%2B86', wire.calls[0][1])
        self.assertNotIn('13800000000', repr(client))

    def test_missing_session_stops_before_network(self):
        wire = Transport()
        with self.assertRaises(ApiError):
            Client(transport=wire).vehicles()
        self.assertFalse(wire.calls)

    def test_unknown_operation_rejected(self):
        with self.assertRaises(ApiError):
            Client()._request('unlock')

    def test_sms_login_keeps_only_read_session(self):
        wire = Transport(ok({'jwtToken': 'jwt'}), ok({'YIKAT_NEW': 'code'}),
                         ok({'accessToken': 'a', 'userId': 'u', 'clientId': 'c'}))
        client = Client(transport=wire)
        client.login_sms('13800000000', '123456')
        self.assertEqual(set(client.session), {'deviceId', 'accessToken', 'userId', 'clientId'})
        login_body = json.loads(wire.calls[0][3])
        self.assertEqual(login_body['smsCode'], '123456')
        self.assertEqual(login_body['deviceId'], wire.calls[0][2]['device_id'])
        self.assertEqual(wire.calls[1][2]['Authorization'], 'jwt')
