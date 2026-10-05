import http.client
import tempfile
import threading
import unittest
from pathlib import Path
from zeekr_control.web import App, make_server, STATIC, VERSIONED_IMAGES
import hashlib
from zeekr_control.auth import WebAuth, password_record


class ImageDeliveryTests(unittest.TestCase):
    def test_images_revalidate_but_auth_and_data_never_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(Path(tmp) / 'session.json')
            auth = WebAuth(password_record('test password 12345'))
            server = make_server(app, 0, auth=auth)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cookie = 'zeekr_session=' + auth.login('test password 12345')
            def get(path, headers=None):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                connection.request('GET', path, headers=headers or {})
                response = connection.getresponse()
                result = response.status, dict(response.getheaders()), response.read()
                connection.close()
                return result
            try:
                status, headers, body = get('/car.svg', {'Cookie': cookie})
                self.assertEqual(status, 200)
                self.assertEqual(headers['Cache-Control'], 'private, no-cache')
                etag = headers['ETag']
                self.assertTrue(body)
                status, headers, body = get('/car.svg', {'Cookie': cookie, 'If-None-Match': etag})
                self.assertEqual(status, 304)
                self.assertEqual(body, b'')
                self.assertEqual(get('/car.svg', {'If-None-Match': etag})[0], 401)
                self.assertEqual(get('/api/state', {'Cookie': cookie})[1]['Cache-Control'], 'no-store')
                self.assertEqual(get('/app.js', {'Cookie': cookie})[1]['Cache-Control'], 'no-store')
                for name in VERSIONED_IMAGES:
                    payload = (STATIC / name).read_bytes()
                    self.assertIn(hashlib.sha256(payload).hexdigest()[:12], name)
                    self.assertLess(len(payload), 110000)
                    self.assertEqual(payload[8:12], b'WEBP')
                    self.assertEqual(get('/' + name)[0], 401)
                    status, headers, body = get('/' + name, {'Cookie': cookie})
                    self.assertEqual(status, 200)
                    self.assertEqual(headers['Content-Type'], 'image/webp')
                    self.assertEqual(headers['Cache-Control'], 'private, max-age=86400, immutable')
                    self.assertEqual(body, payload)
            finally:
                server.shutdown(); server.server_close(); app.close(); thread.join()
