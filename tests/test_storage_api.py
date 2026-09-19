"""Authenticated storage maintenance using synthetic archives only."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from zeekr_control.auth import WebAuth, password_record
from zeekr_control.snapshots import SnapshotStore
from zeekr_control.web import App, make_server


class StorageAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = App(Path(self.temp.name)/'private/session.json')
        self.auth = WebAuth(password_record('synthetic-test-password'))
        self.server = make_server(self.app, 0, auth=self.auth)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:%d' % self.server.server_port
        self.cookie = 'zeekr_session='+self.auth.login('synthetic-test-password')
        self.key = self.app.request_key
        SnapshotStore(self.app.session_path.parent/'snapshots.sqlite3').publish(
            'private-scope', 'private-vehicle', {'secret': 'PRIVATE-RAW'}, 1733011200000)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.app.close(); self.temp.cleanup()

    def request(self, method, path, data=None, cookie=None, origin=None, key=None):
        headers = {'Cookie': self.cookie if cookie is None else cookie,
                   'Origin': origin or self.origin, 'X-Request-Key': self.key if key is None else key,
                   'Content-Type': 'application/json'}
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request(method, path, json.dumps(data) if data is not None else None, headers)
        response = connection.getresponse()
        result = response.status, response.read().decode()
        connection.close()
        return result

    def test_anonymous_and_csrf_rejected_for_all_storage_routes(self):
        for method, path in [('GET','/api/storage'), ('GET','/api/storage/archives'),
                             ('GET','/storage-management.js'), ('GET','/storage-management.css'),
                             ('POST','/api/storage/preview'), ('POST','/api/storage/execute')]:
            self.assertEqual(self.request(method, path, {}, cookie='')[0], 401)
        for path in ('/api/storage/preview', '/api/storage/execute'):
            self.assertEqual(self.request('POST', path, {}, key='wrong')[0], 403)
            self.assertEqual(self.request('POST', path, {}, origin='https://evil.invalid')[0], 403)

    def test_projection_confirmation_and_session_binding(self):
        for path in ('/api/storage', '/api/storage/archives'):
            code, body = self.request('GET', path)
            self.assertEqual(code, 200)
            for secret in ('PRIVATE-RAW', 'private-scope', 'private-vehicle', str(self.app.session_path.parent)):
                self.assertNotIn(secret, body)
        code, body = self.request('POST', '/api/storage/preview', {'action':'trash','target':'2024/12'})
        self.assertEqual(code, 200)
        plan = json.loads(body)
        self.assertNotIn('fingerprint', plan)
        command = {'token':plan['token'], 'confirmation':plan['confirmation']}
        other = 'zeekr_session='+self.auth.login('synthetic-test-password')
        self.assertEqual(self.request('POST', '/api/storage/execute', command, cookie=other)[0], 400)
        wrong = dict(command, confirmation='删除')
        self.assertEqual(self.request('POST', '/api/storage/execute', wrong)[0], 400)
        self.assertEqual(self.request('POST', '/api/storage/execute', command)[0], 200)
        self.assertEqual(self.request('POST', '/api/storage/execute', command)[0], 400)

    def test_arbitrary_paths_and_raw_archive_download_forbidden(self):
        self.assertEqual(self.request('POST', '/api/storage/preview', {'action':'trash','target':'../session.json'})[0], 400)
        self.assertEqual(self.request('GET', '/snapshot-archive/2024/12.sqlite3')[0], 404)
