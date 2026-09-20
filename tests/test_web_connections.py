import http.client
from email.message import Message
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from zeekr_control.web import App,make_server


class WebConnectionTests(unittest.TestCase):
    def test_disconnected_response_is_not_retried_as_server_error(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            app=App(Path(directory)/'session.json');stack.callback(app.close)
            server=make_server(app,0);stack.callback(server.server_close)
            for error in (BrokenPipeError,ConnectionResetError):
                for failed_write in (1,2):
                    with self.subTest(error=error.__name__,failed_write=failed_write):
                        handler=server.RequestHandlerClass.__new__(server.RequestHandlerClass)
                        handler.server=server;handler.path='/api/state'
                        handler.headers=Message();handler.headers['Host']='127.0.0.1:%d'%server.server_port
                        handler.request_version='HTTP/1.1';handler.requestline='GET /api/state HTTP/1.1'
                        handler.command='GET';handler.close_connection=False
                        handler.wfile=Mock()
                        handler.wfile.write.side_effect=[None]*(failed_write-1)+[error('client closed')]
                        with patch.object(app,'state',return_value={'connected':False}),patch.object(handler,'send_response',wraps=handler.send_response) as responses:
                            handler.do_GET()
                        self.assertEqual([call.args[0] for call in responses.call_args_list],[200])
                        self.assertEqual(handler.wfile.write.call_count,failed_write)
                        self.assertTrue(handler.close_connection)

    def test_response_does_not_suppress_unrelated_io_failure(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            app=App(Path(directory)/'session.json');stack.callback(app.close)
            server=make_server(app,0);stack.callback(server.server_close)
            handler=server.RequestHandlerClass.__new__(server.RequestHandlerClass)
            handler.request_version='HTTP/1.1';handler.requestline='GET / HTTP/1.1';handler.command='GET'
            handler.wfile=Mock();handler.wfile.write.side_effect=OSError('other failure')
            with self.assertRaises(OSError):handler.send(200,{})

    def test_asset_connection_burst_can_queue_before_accept_loop(self):
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            app=App(Path(directory)/'session.json');stack.callback(app.close)
            server=make_server(app,0);stack.callback(server.server_close)
            # Browser tabs can open many asset sockets before the Python accept
            # loop gets its next timeslice. No requests or threads are needed yet.
            for _ in range(24):
                stack.enter_context(socket.create_connection(('127.0.0.1',server.server_port),timeout=.3))

    def test_concurrent_asset_responses_remain_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            app=App(Path(directory)/'session.json');server=make_server(app,0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                def fetch(index):
                    path=('/app.js','/insights.js','/charge-comparison.js','/theme.css')[index%4]
                    c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                    try:
                        c.request('GET',path);r=c.getresponse();body=r.read()
                        return r.status,len(body),int(r.getheader('Content-Length'))
                    finally:c.close()
                with ThreadPoolExecutor(max_workers=24) as pool:
                    rows=list(pool.map(fetch,range(96)))
                self.assertTrue(all(status==200 and size==expected and size>0 for status,size,expected in rows))
            finally:server.shutdown();server.server_close();thread.join();app.close()


if __name__=='__main__':unittest.main()
