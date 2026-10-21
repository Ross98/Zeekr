"""Tailscale Serve is an explicit proxy mode, never a blanket XFF trust."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from zeekr_control.auth import WebAuth, password_record
from zeekr_control.web import make_server


class TailscaleProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = password_record('synthetic password')

    def request(self, headers, days=7, enabled=True, public=True):
        with tempfile.TemporaryDirectory() as folder:
            auth = WebAuth(self.record, Path(folder)/'remembered.sqlite3')
            app = SimpleNamespace(request_key='synthetic')
            server = make_server(app, 0, auth=auth, public_origin='https://test.ts.net',
                                 tailscale_proxy=enabled)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                host = 'test.ts.net' if public else '127.0.0.1:%d' % server.server_port
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                base = {'Host': host, 'Origin': ('https://' if public else 'http://')+host,
                        'User-Agent': 'Synthetic Browser', 'Content-Type': 'application/json'}
                base.update(headers)
                connection.request('POST', '/auth/login', json.dumps({
                    'password': 'synthetic password', 'remember_days': days}), base)
                response = connection.getresponse()
                status = response.status
                cookie = response.getheader('Set-Cookie')
                response.read(); connection.close()
                if status == 200:
                    token = cookie.split(';')[0].split('=', 1)[1]
                    expected = headers.get('X-Forwarded-For') if public else '127.0.0.1'
                    self.assertTrue(auth.valid(token, client_ip=expected, user_agent='Synthetic Browser'))
                return status, cookie
            finally:
                server.shutdown(); server.server_close(); worker.join()

    def test_remembered_login_accepts_single_tailnet_ip(self):
        for ip, days in [('100.64.0.2', 7), ('fd7a:115c:a1e0::2', 30)]:
            with self.subTest(ip=ip):
                code, cookie = self.request({'X-Forwarded-For': ip, 'X-Forwarded-Proto': 'https',
                                             'X-Real-IP': '192.0.2.9'}, days)
                self.assertEqual(code, 200)
                self.assertIn('Secure', cookie)

    def test_absent_forged_or_ambiguous_context_cannot_issue_remembered_cookie(self):
        for headers in [{}, {'X-Real-IP': '100.64.0.2'},
                        {'X-Forwarded-For': '192.0.2.9'},
                        {'X-Forwarded-For': '127.0.0.1'},
                        {'X-Forwarded-For': '100.64.0.2, 100.64.0.3'},
                        {'X-Forwarded-For': 'garbage'},
                        {'X-Forwarded-For': '100.64.0.2', 'X-Forwarded-Proto': 'http'}]:
            with self.subTest(headers=headers):
                headers = {'X-Forwarded-Proto': 'https', **headers}
                self.assertEqual(self.request(headers), (400, None))
        self.assertEqual(self.request({'X-Forwarded-For': '100.64.0.2',
                                       'X-Forwarded-Proto': 'https'}, enabled=False), (400, None))

    def test_local_entry_ignores_forwarded_headers(self):
        self.assertEqual(self.request({'X-Forwarded-For': '100.64.0.2',
                                       'X-Forwarded-Proto': 'https'}, public=False)[0], 200)

    def test_proxy_modes_cannot_be_combined(self):
        with self.assertRaises(ValueError):
            make_server(SimpleNamespace(), 0, trusted_proxy=True, tailscale_proxy=True)

    def test_duplicate_headers_and_nonloopback_proxy_rejected(self):
        from email.message import Message
        for peer, xff, proto in [
                ('192.0.2.2',['100.64.0.2'],['https']),
                ('127.0.0.1',['100.64.0.2','100.64.0.3'],['https']),
                ('127.0.0.1',['100.64.0.2'],['https','https'])]:
            server=make_server(SimpleNamespace(),0,auth=object(),public_origin='https://test.ts.net',tailscale_proxy=True)
            try:
                headers=Message();headers['Host']='test.ts.net'
                for ip in xff:headers['X-Forwarded-For']=ip
                for value in proto:headers['X-Forwarded-Proto']=value
                request=SimpleNamespace(headers=headers,client_address=(peer,1234))
                self.assertEqual(server.RequestHandlerClass.client_ip(request),'')
            finally:server.server_close()
