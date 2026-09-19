"""Temporary synthetic fixture; no vehicle network or real notification sender."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
from web_fixture import App, FixtureClient, make_server, save
from zeekr_control.snapshots import SnapshotStore
from zeekr_control.storage_health import StorageHealth

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)/'private'
    save(root/'session.json', {'accessToken':'TEST-ONLY', 'userId':'TEST-ONLY'})
    store = SnapshotStore(root/'snapshots.sqlite3')
    store.publish('scope','vehicle',{'synthetic':True},int(datetime(2024,12,1,tzinfo=timezone.utc).timestamp()*1000))
    store.publish('scope','vehicle',{'synthetic':True},int(time.time()*1000))
    StorageHealth(root, sender=lambda message: None).tick()
    app = App(root/'session.json', client_factory=FixtureClient)
    server = make_server(app, 0)
    print(server.server_port, flush=True)
    try: server.serve_forever()
    finally: app.close(); server.server_close()
