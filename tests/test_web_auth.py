import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from zeekr_control.web import App, make_server

class AuthTests(unittest.TestCase):
    def test_authentication_is_available(self):
        import zeekr_control.web as web
        self.assertTrue(hasattr(web, 'WebAuth'), 'Missing authentication gate')

    def test_protected_routes_login_logout_and_expiry(self):
        from zeekr_control.auth import WebAuth, password_record
        with tempfile.TemporaryDirectory() as tmp:
            auth = WebAuth(password_record('test password 12345'))
            app = App(Path(tmp)/'session.json')
            server = make_server(app, 0, auth=auth, public_origin='https://zeekr.example.com')
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(method,path,body=None,cookie='',origin=None):
                c=http.client.HTTPConnection('127.0.0.1',server.server_port)
                headers={'Host':'zeekr.example.com','Cookie':cookie}
                if origin: headers['Origin']=origin
                if body is not None: headers['Content-Type']='application/json'
                c.request(method,path,json.dumps(body) if body is not None else None,headers)
                r=c.getresponse(); result=(r.status,dict(r.getheaders()),r.read());c.close();return result
            try:
                for route in ['/api/state','/api/location','/api/tracks','/api/history?date=2024-01-01','/api/history/points?trip=unknown','/history.js','/car.svg','/app.js']:
                    self.assertEqual(request('GET',route)[0],401)
                self.assertEqual(request('GET','/')[0],200)
                self.assertEqual(request('POST','/api/refresh',{'vehicle':1})[0],401)
                self.assertEqual(request('POST','/api/recording',{'active':True})[0],401)
                self.assertEqual(request('GET','/api/state',cookie='zeekr_session=forged')[0],401)
                self.assertEqual(request('POST','/auth/login',{'password':'wrong'},origin='https://zeekr.example.com')[0],401)
                self.assertEqual(request('POST','/auth/login',{'password':'test password 12345'},origin='https://evil.example')[0],403)
                status,headers,_=request('POST','/auth/login',{'password':'test password 12345'},origin='https://zeekr.example.com')
                self.assertEqual(status,200)
                self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('Secure',headers['Set-Cookie'])
                cookie=headers['Set-Cookie'].split(';')[0]
                self.assertEqual(request('GET','/api/state',cookie=cookie)[0],200)
                self.assertEqual(request('POST','/api/recording',{'active':True},cookie,'https://zeekr.example.com')[0],403)
                self.assertFalse(WebAuth(password_record('test password 12345')).valid(cookie.split('=',1)[1]))
                self.assertEqual(request('POST','/auth/logout',{},cookie, 'https://zeekr.example.com')[0],200)
                self.assertEqual(request('GET','/api/state',cookie=cookie)[0],401)
                token=auth.login('test password 12345')
                with patch('zeekr_control.auth.time.time',return_value=10**12):
                    self.assertFalse(auth.valid(token))
                for _ in range(5): auth.login('wrong')
                self.assertTrue(auth.limited())
                self.assertIsNone(auth.login('test password 12345'))
            finally:
                server.shutdown();server.server_close();app.close();thread.join()
