"""Synthetic local trip browser fixture; no owner files or gateway requests."""
from datetime import datetime
import json
from pathlib import Path
import tempfile

from web_fixture import FixtureClient
from zeekr_control.storage import save
from zeekr_control.web import App, make_server
from zeekr_control.monitor import Monitor


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        session = Path(directory) / 'private' / 'session.json'
        save(session, {'accessToken': 'TEST-ONLY', 'userId': 'TEST-ONLY'})
        app = App(session, client_factory=FixtureClient)
        app.refresh(1)
        store = Monitor(app.database_path).tracks
        start = int(datetime.fromisoformat('2024-01-01T23:58:00+08:00').timestamp() * 1000)
        trips = [('night-trip', start, 720, 9.6), ('morning-trip', start + 36000000, 1200, 16.8)]
        for event_id, begin, seconds, distance in trips:
            summary = {'start_time': begin, 'end_time': begin + seconds * 1000,
                       'duration_seconds': seconds, 'distance_km': distance,
                       'start_soc': 70, 'end_soc': 68, 'soc_delta': -2,
                       'partial': event_id == 'morning-trip', 'battery_capacity_kwh': 86}
            with store.connect() as db:
                db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                           (event_id, app.vehicle_key, 'trip_end', json.dumps(summary), 'PRIVATE', summary['end_time']))
            for index, seconds in enumerate([0, 60, 120, 240, 600, 660, seconds]):
                timestamp = begin + seconds * 1000
                store.record(app.vehicle_key, {'updateTime': timestamp, 'position': {
                    'latitude': 111600000 + index * 9000, 'longitude': 435600000 + index * 16000,
                    'posCanBeTrusted': index != 3, 'marsCoordinates': False}}, timestamp + 5000, 180)
        server = make_server(app, 0)
        print(server.server_port, flush=True)
        try:
            server.serve_forever()
        finally:
            app.close()
            server.server_close()
