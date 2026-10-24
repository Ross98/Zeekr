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
    def test_bad_resource_fields_do_not_break_readonly_storage_page(self):
        from unittest.mock import patch
        from zeekr_control.resource_monitor import ResourceHealth
        health=ResourceHealth(self.app.session_path.parent)
        cases=(
            ({'host_cpu_percent':10**400,'app_rss_bytes':10**400}, {}, 'healthy'),
            ({}, {'endpoint:local':{'level':[]}}, 'unknown'),
            ({}, {'endpoint:local':[]}, 'unknown'),
            ({}, [], 'unknown'),
            ({}, {'endpoint:local':{'level':{}},'service:local.zeekr.web':{'level':'critical'}}, 'critical'),
            ({}, {'memory_pressure':{'level':{}}}, 'healthy'),
        )
        for sample,conditions,expected_level in cases:
            with self.subTest(expected_level=expected_level,conditions=str(conditions)[:80]):
                sample=dict(sample,physical_memory_bytes=16*1024**3,app_cpu_percent=0,private_token='PRIVATE-RESOURCE')
                health.save({'checked_at':1000,'sample':sample,'conditions':conditions})
                before=health.path.read_bytes()
                with patch('zeekr_control.resource_monitor.time.time',return_value=1000),\
                     patch('zeekr_control.resource_monitor.NativeSampler.measure',side_effect=AssertionError('must not sample')):
                    code,body=self.request('GET','/api/storage')
                self.assertEqual(code,200,body)
                result=json.loads(body)['resources']
                self.assertEqual(result['alert_level'],expected_level)
                self.assertEqual(result['application']['cpu_percent'],0)
                self.assertEqual(result['host']['physical_memory_bytes'],16*1024**3)
                if 'app_rss_bytes' in sample:self.assertIsNone(result['application']['rss_bytes'])
                self.assertEqual(health.path.read_bytes(),before)
                self.assertNotIn('PRIVATE-RESOURCE',body)

    def test_broken_monitor_cache_does_not_hide_current_storage_or_rewrite_state(self):
        from unittest.mock import patch
        from zeekr_control.storage import save
        path=self.app.session_path.parent/'storage-health.json'
        sample={'disk_used_percent':50,'disk_free_bytes':20*1024**3,'scan_complete':True}
        for state in ('null','[]','{"sample":[]}','{"sample":"PRIVATE"}'):
            with self.subTest(state=state):
                save(path,{'state':state});before=path.read_bytes()
                with patch('zeekr_control.storage_health.StorageHealth.measure',return_value=sample):
                    code,body=self.request('GET','/api/storage')
                self.assertEqual(code,200)
                result=json.loads(body)
                self.assertEqual(result['current']['disk_free_bytes'],20*1024**3)
                self.assertEqual(result['monitor']['status'],'unknown')
                self.assertFalse(result['monitor']['monitor_fresh'])
                self.assertEqual(path.read_bytes(),before)
                self.assertNotIn('PRIVATE',body)

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

    def test_resource_reference_is_authenticated_cached_and_sanitized(self):
        from unittest.mock import patch
        from zeekr_control.resource_monitor import ResourceHealth
        health=ResourceHealth(self.app.session_path.parent)
        health.save(dict(checked_at=1000, sample=dict(host_cpu_percent=99,memory_pressure='critical',
            app_rss_bytes=0,private_token='PRIVATE-RESOURCE'),conditions={}))
        with patch('zeekr_control.resource_monitor.NativeSampler.measure',side_effect=AssertionError('must use cache')):
            code,body=self.request('GET','/api/storage')
        self.assertEqual(code,200)
        data=json.loads(body)['resources']
        self.assertFalse(data['fresh'])
        self.assertEqual(data['host']['memory_pressure'],'critical')
        self.assertEqual(data['application']['rss_bytes'],0)
        self.assertNotIn('PRIVATE-RESOURCE',body)

    def test_arbitrary_paths_and_raw_archive_download_forbidden(self):
        self.assertEqual(self.request('POST', '/api/storage/preview', {'action':'trash','target':'../session.json'})[0], 400)
        self.assertEqual(self.request('GET', '/snapshot-archive/2024/12.sqlite3')[0], 404)
