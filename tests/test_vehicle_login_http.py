"""Exercise SMS API authentication and same-origin mutation boundaries offline."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from zeekr_control.web import App, make_server


class VehicleLoginHTTPTests(unittest.TestCase):
    def request(self, path, headers):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('POST', path, json.dumps({'phone': '13800000000'}), headers)
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result

    def test_routes_use_auth_origin_request_key_and_browser_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            app = App(Path(directory) / 'session.json')
            app.vehicle_login = Mock()
            app.vehicle_login.send.return_value = (200, {'challenge': 'safe'})
            app.vehicle_login.verify.return_value = (200, {'connected': True})
            auth = Mock()
            auth.valid.return_value = False
            self.server = make_server(app, port=0, auth=auth)
            thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            thread.start()
            try:
                origin = 'http://127.0.0.1:%d' % self.server.server_port
                headers = {'Origin': origin, 'X-Request-Key': app.request_key,
                           'Content-Type': 'application/json', 'Cookie': 'zeekr_session=browser-one'}
                self.assertEqual(self.request('/api/vehicle-login/sms', headers)[0], 401)
                auth.valid.return_value = True
                self.assertEqual(self.request('/api/vehicle-login/sms', {**headers, 'Origin': 'https://evil.invalid'})[0], 403)
                self.assertEqual(self.request('/api/vehicle-login/sms', {**headers, 'X-Request-Key': ''})[0], 403)
                app.vehicle_login.send.assert_not_called()
                self.assertEqual(self.request('/api/vehicle-login/sms', headers)[0], 200)
                self.assertEqual(self.request('/api/vehicle-login/verify', headers)[0], 200)
                self.assertNotIn('browser-one', str(app.vehicle_login.send.call_args))
                self.assertEqual(app.vehicle_login.send.call_args.args[1], app.vehicle_login.verify.call_args.args[1])
            finally:
                self.server.shutdown()
                self.server.server_close()
                thread.join()
                app.close()
