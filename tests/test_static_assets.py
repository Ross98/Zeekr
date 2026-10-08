import hashlib
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest

from zeekr_control.auth import WebAuth, password_record
from zeekr_control.web import App, STATIC, make_server


class StaticAssetsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = App(Path(self.folder.name)/'session.json')
        self.addCleanup(self.app.close)
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def get(self, path, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request('GET',path,headers=headers or {})
        response=connection.getresponse()
        result=response.status,dict(response.getheaders()),response.read()
        connection.close()
        return result

    def test_html_versions_assets_and_manifest_resolves_lazy_modules(self):
        status,headers,html=self.get('/')
        self.assertEqual(status,200)
        self.assertIn('no-store',headers['Cache-Control'])
        match=re.search(rb'src="(/app.js\?v=[a-f0-9]{16})"',html)
        self.assertIsNotNone(match)
        status,headers,body=self.get(match[1].decode())
        self.assertEqual(status,200)
        self.assertIn('immutable',headers['Cache-Control'])
        self.assertEqual(body,(STATIC/'app.js').read_bytes())
        status,headers,body=self.get(match[1].decode(),{'If-None-Match':headers['ETag']})
        self.assertEqual((status,body),(304,b''))
        status,_,body=self.get('/asset-manifest.js')
        self.assertEqual(status,200)
        self.assertIn(b'ZeekrAssets',body)
        digest=hashlib.sha256((STATIC/'hypothesis-lab.js').read_bytes()).hexdigest()[:16]
        self.assertIn(('/hypothesis-lab.js?v='+digest).encode(),body)

    def test_unversioned_or_wrong_versions_never_get_immutable_cache(self):
        for path in ('/app.js','/app.js?v=old-version'):
            status,headers,_=self.get(path)
            self.assertEqual(status,200)
            self.assertNotIn('immutable',headers['Cache-Control'])
        self.assertEqual(self.get('/api/state')[1]['Cache-Control'],'no-store')

    def test_protected_assets_stay_protected_even_with_version_query(self):
        auth=WebAuth(password_record('synthetic password'))
        server=make_server(self.app,0,auth=auth)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for path in ('/app.js?v=abc','/asset-manifest.js','/api/insights/costs?date=2026-10-08',
                         '/api/notifications/health'):
                c=http.client.HTTPConnection('127.0.0.1',server.server_port)
                c.request('GET',path);r=c.getresponse();r.read();c.close()
                self.assertEqual(r.status,401,path)
            c=http.client.HTTPConnection('127.0.0.1',server.server_port)
            c.request('GET','/login.js?v=abc');r=c.getresponse();r.read();c.close()
            self.assertEqual(r.status,200)
        finally:server.shutdown();server.server_close();thread.join()
