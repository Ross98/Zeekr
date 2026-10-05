import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from zeekr_control.auth import WebAuth, password_record
from zeekr_control.web import App, make_server


class RememberedAuthHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = password_record('synthetic http password')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.auth = WebAuth(self.record, remembered_path=self.path / 'remembered.sqlite3')
        self.app = App(self.path / 'session.json')
        self.addCleanup(self.app.close)
        self.server = make_server(self.app, 0, auth=self.auth,
                                  public_origin='https://zeekr.example.com', trusted_proxy=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, cookie='', ip='192.0.2.10',
                agent='Synthetic Browser', public=True, origin=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        host = 'zeekr.example.com' if public else '127.0.0.1:%d' % self.server.server_port
        headers = {'Host': host, 'Cookie': cookie, 'User-Agent': agent}
        if ip is not None:
            headers['X-Real-IP'] = ip
        if method == 'POST':
            headers['Content-Type'] = 'application/json'
            headers['Origin'] = origin or ('https://' if public else 'http://') + host
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def login(self, days=7, **kwargs):
        return self.request('POST', '/auth/login',
                            {'password': 'synthetic http password', 'remember_days': days}, **kwargs)

    def test_http_cookie_durations_context_restart_and_logout(self):
        for days in (7, 30):
            with self.subTest(days=days):
                status, headers, _ = self.login(days)
                self.assertEqual(status, 200)
                for attribute in ('HttpOnly', 'SameSite=Strict', 'Secure', 'Max-Age=%d' % (days * 86400)):
                    self.assertIn(attribute, headers['Set-Cookie'])
                cookie = headers['Set-Cookie'].split(';')[0]
                self.auth.sessions.clear()  # Persistent sessions must not depend on normal sessions.
                self.assertEqual(self.request('GET', '/api/state', cookie=cookie)[0], 200)
                self.assertEqual(self.request('GET', '/api/state', cookie=cookie, ip='192.0.2.11')[0], 401)
                self.assertEqual(self.request('GET', '/api/state', cookie=cookie, agent='Other Browser')[0], 401)
                self.assertEqual(self.request('GET', '/api/state', cookie=cookie, ip=None)[0], 401)
                self.assertEqual(self.request('GET', '/api/state', cookie=cookie, ip='garbage')[0], 401)
                self.assertEqual(self.request('POST', '/auth/logout', {}, cookie=cookie)[0], 200)
                restarted = WebAuth(self.record, remembered_path=self.path / 'remembered.sqlite3')
                self.assertFalse(restarted.valid(cookie.split('=', 1)[1], client_ip='192.0.2.10',
                                                 user_agent='Synthetic Browser'))
                self.assertEqual(self.request('GET', '/api/state', cookie=cookie)[0], 401)

    def test_invalid_duration_missing_context_and_cross_origin_do_not_issue_cookie(self):
        for value in (True, False, 7.0, '7', 1, -1, 31, None):
            with self.subTest(value=value):
                status, headers, _ = self.login(value)
                self.assertEqual(status, 400)
                self.assertNotIn('Set-Cookie', headers)
        self.assertEqual(self.login(ip=None)[0], 400)
        self.assertEqual(self.login(ip='192.0.2.10, 127.0.0.1')[0], 400)
        self.assertEqual(self.login(agent='')[0], 400)
        self.assertEqual(self.login(origin='https://evil.example')[0], 403)
        status, headers, _ = self.request('POST', '/auth/login', {'password': 'wrong', 'remember_days': 7})
        self.assertEqual(status, 401)
        self.assertNotIn('Set-Cookie', headers)

    def test_default_login_replaces_and_revokes_old_remembered_credential(self):
        cookie = self.login()[1]['Set-Cookie'].split(';')[0]
        status, headers, _ = self.login(0, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn('Max-Age=43200', headers['Set-Cookie'])
        self.assertEqual(self.request('GET', '/api/state', cookie=cookie)[0], 401)
        current = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('GET', '/api/state', cookie=current)[0], 200)
        restarted = WebAuth(self.record, remembered_path=self.path / 'remembered.sqlite3')
        self.assertFalse(restarted.valid(current.split('=', 1)[1], client_ip='192.0.2.10',
                                         user_agent='Synthetic Browser'))

    def test_local_connection_ignores_forged_forwarding_header(self):
        status, headers, _ = self.login(public=False)
        self.assertEqual(status, 200)
        self.assertNotIn('Secure', headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';')[0]
        token = cookie.split('=', 1)[1]
        self.assertTrue(self.auth.valid(token, client_ip='127.0.0.1', user_agent='Synthetic Browser'))
        self.assertFalse(self.auth.valid(token, client_ip='192.0.2.10', user_agent='Synthetic Browser'))
        self.assertEqual(self.request('GET', '/api/state', cookie=cookie, public=False, ip='192.0.2.99')[0], 200)

    def test_unconfigured_public_proxy_cannot_claim_ip_binding(self):
        isolated = make_server(self.app, 0, auth=self.auth, public_origin='https://zeekr.example.com')
        thread = threading.Thread(target=isolated.serve_forever, daemon=True)
        thread.start()
        previous = self.server
        try:
            self.server = isolated
            self.assertEqual(self.login()[0], 400)
            self.assertEqual(self.login(0)[0], 200)
        finally:
            self.server = previous
            isolated.shutdown()
            isolated.server_close()
            thread.join()

    def test_storage_errors_have_actionable_response_and_logout_not_claimed(self):
        cookie = self.login()[1]['Set-Cookie'].split(';')[0]
        with patch.object(self.auth, '_connect', side_effect=OSError('synthetic private error')):
            for method, path, body in [('POST', '/auth/login', {'password': 'synthetic http password', 'remember_days': 7}),
                                       ('POST', '/auth/logout', {})]:
                status, headers, payload = self.request(method, path, body, cookie=cookie)
                self.assertEqual(status, 503)
                self.assertNotIn('Set-Cookie', headers)
                self.assertNotIn(b'synthetic private error', payload)
            self.assertEqual(self.request('GET', '/api/state', cookie=cookie)[0], 401)
