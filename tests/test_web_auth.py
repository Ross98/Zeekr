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
                self.assertEqual(request('GET','/route-quality.js')[0],401)
                self.assertEqual(request('GET','/charge-management.js')[0],401)
                self.assertEqual(request('GET','/api/charging/manage?start=2024-01-01&end=2024-01-02')[0],401)
                for route in ['/daily-recall.js','/api/timeline?date=2026-09-20','/api/place-corrections?date=2026-09-20','/api/place-history?start=2026-09-01&end=2026-09-30&key=bad','/api/year-review?year=2026','/trip-management.js','/api/trips/manage?start=2024-01-01&end=2024-01-02','/data-quality.js','/api/insights/quality?start=2026-09-20&end=2026-09-20','/vehicle-life.js','/api/insights/life?date=2026-09-20','/usage-calendar.js','/api/insights/calendar?date=2026-09-20','/parameter-experiments.js','/api/insights/experiments','/api/insights/experiments/detail?id=missing','/charge-comparison.js','/api/insights/charge-comparison?a=a&b=b','/api/insights/charge-comparison/options?date=2026-07-12','/trip-tags.js','/api/insights/trip-tags?date=2026-09-20','/custom-reminders.js','/api/insights/rules','/api/insights/ledger?date=2026-09-20','/charge-ledger.js','/api/insights/report?period=month&date=2026-09-20','/usage-reports.js','/api/insights/parking?start=2026-09-20&end=2026-09-20','/parking.js','/api/insights/timeline?date=2026-09-20','/api/insights/snapshot?id=202609.1','/api/insights/compare?before=202609.1&after=202609.2','/insights.js','/insights.css','/api/state','/api/vehicle/parameters','/vehicle.js','/vehicle.css','/api/location','/api/tracks','/api/trips?date=2024-01-02','/api/tracks?date=2024-01-02&trip=current','/api/history?date=2024-01-01','/api/history/points?trip=unknown','/api/charging/process?id=current&view=power-soc','/history.js','/car.svg','/app.js','/trips.js','/trips.css']:
                    self.assertEqual(request('GET',route)[0],401)
                self.assertEqual(request('GET','/')[0],200)
                login_html = request('GET', '/')[2].decode()
                self.assertIn('rel="icon" href="/zeekr-logo.png"', login_html)
                self.assertNotIn('<img', login_html)
                for asset in ('/theme.js', '/theme.css', '/login.js', '/login.css', '/zeekr-logo.png'):
                    status, headers, body = request('GET', asset)
                    self.assertEqual(status, 200, asset)
                    self.assertTrue(body)
                    self.assertNotIn('text/html', headers['Content-Type'])
                self.assertEqual(request('GET', '/zeekr-logo.png')[1]['Content-Type'], 'image/png')
                self.assertEqual(request('GET','/theme.js/../app.js')[0],401)
                self.assertEqual(request('POST','/api/refresh',{'vehicle':1})[0],401)
                for route in ('/api/place-corrections','/api/trips/manage/preview','/api/trips/manage/execute'):
                    self.assertEqual(request('POST',route,{})[0],401)
                for route in ('/api/charging/manage/preview','/api/charging/manage/execute'):
                    self.assertEqual(request('POST',route,{})[0],401)
                self.assertEqual(request('POST','/api/recording',{'active':True})[0],401)
                self.assertEqual(request('GET','/api/state',cookie='zeekr_session=forged')[0],401)
                self.assertEqual(request('POST','/auth/login',{'password':'wrong'},origin='https://zeekr.example.com')[0],401)
                self.assertEqual(request('POST','/auth/login',{'password':'test password 12345'},origin='https://evil.example')[0],403)
                status,headers,_=request('POST','/auth/login',{'password':'test password 12345'},origin='https://zeekr.example.com')
                self.assertEqual(status,200)
                self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('Secure',headers['Set-Cookie'])
                cookie=headers['Set-Cookie'].split(';')[0]
                dashboard_html = request('GET', '/', cookie=cookie)[2].decode()
                self.assertIn('rel="icon" href="/zeekr-logo.png"', dashboard_html)
                self.assertNotIn('class="brand-logo"', dashboard_html)
                self.assertEqual(request('GET','/api/state',cookie=cookie)[0],200)
                self.assertEqual(request('GET','/charge-management.js',cookie=cookie)[0],200)
                for asset in ('/route-quality.js', '/trip-management.js', '/trips.js', '/trips.css', '/vehicle.js', '/vehicle.css', '/api/vehicle/parameters'):
                    status, headers, body = request('GET', asset, cookie=cookie)
                    self.assertEqual(status, 200, asset)
                    self.assertTrue(body)
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
