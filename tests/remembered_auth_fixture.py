"""Synthetic login fixture; restart real server without discarding browser state."""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zeekr_control.auth import WebAuth, password_record
from zeekr_control.web import App, make_server


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    record = password_record('synthetic browser password')
    app = App(root / 'session.json')

    def start(port):
        auth = WebAuth(record, remembered_path=root / 'web-remembered.sqlite3')
        server = make_server(app, port, auth=auth)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    server, thread = start(0)
    print(server.server_port, flush=True)
    try:
        for command in sys.stdin:
            if command.strip() == 'restart':
                port = server.server_port
                server.shutdown()
                server.server_close()
                thread.join()
                server, thread = start(port)
                print('restarted', flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        app.close()
