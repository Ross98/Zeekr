"""Malformed requests must fail before authentication or local mutations."""
from contextlib import ExitStack
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from zeekr_control.auth import WebAuth, password_record
from zeekr_control.web import App, make_server


class JsonBoundaryTests(unittest.TestCase):
    def setUp(self):
        stack=ExitStack();self.addCleanup(stack.close)
        directory=stack.enter_context(tempfile.TemporaryDirectory())
        self.app=App(Path(directory)/'session.json');stack.callback(self.app.close)
        self.auth=WebAuth(password_record('synthetic password'))
        self.server=make_server(self.app,0,auth=self.auth);stack.callback(self.server.server_close)
        self.server.handle_error=Mock()
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        stack.callback(thread.join);stack.callback(self.server.shutdown)
        self.origin='http://127.0.0.1:%d'%self.server.server_port
        self.cookie='zeekr_session='+self.auth.login('synthetic password')

    def request(self,path,body):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            connection.request('POST',path,body,{'Origin':self.origin,'Content-Type':'application/json',
                               'Cookie':self.cookie,'X-Request-Key':self.app.request_key})
            response=connection.getresponse();response.read()
            return response.status
        finally:
            connection.close()

    def test_nested_json_returns_bad_request_on_login_and_mutation(self):
        body='{"value":'+'['*1100+'0'+']'*1100+'}'
        for path in ('/auth/login','/api/recording'):
            with self.subTest(path=path):self.assertEqual(self.request(path,body),400)
        self.server.handle_error.assert_not_called()
        self.assertIsNone(self.app.error)

    def test_invalid_unicode_returns_bad_request_on_login_and_mutation(self):
        for path,body in (('/auth/login',{'password':'\ud800'}),
                          ('/api/recording',{'active':False,'note':'\ud800'})):
            with self.subTest(path=path):self.assertEqual(self.request(path,json.dumps(body)),400)
        self.server.handle_error.assert_not_called()
        self.assertFalse((self.app.session_path.parent/'sampling.json').exists())

    def test_nonfinite_json_cannot_change_sampling(self):
        for value in ('NaN','Infinity','-Infinity','1e999'):
            body='{"active":false,"extra":'+value+'}'
            with self.subTest(value=value):self.assertEqual(self.request('/api/recording',body),400)
        self.assertFalse((self.app.session_path.parent/'sampling.json').exists())

    def test_valid_unicode_and_finite_json_remain_supported(self):
        self.assertEqual(self.request('/auth/login',json.dumps({'password':'中文密码 🚗'})),401)
        self.assertEqual(self.request('/api/recording',json.dumps({'active':False,'interval':30})),200)
