"""Real local APIs with synthetic monitor transitions, no vehicle requests."""
import json
from pathlib import Path
import tempfile

from web_fixture import FixtureClient
from test_monitor import BASE, sample
from zeekr_control.storage import save
from zeekr_control.web import App, make_server
from zeekr_control.monitor import Monitor


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        session = Path(directory)/'private'/'session.json'
        save(session, {'accessToken':'TEST-ONLY','userId':'TEST-ONLY'})
        app = App(session, client_factory=FixtureClient)
        app.refresh(1)
        monitor = Monitor(app.database_path)
        def observe(seconds, observed=None, **values):
            monitor.observe(app.vehicle_key, sample(seconds, **values),
                            BASE+(seconds if observed is None else observed)*1000)
        observe(0)
        observe(60, observed=80, speed=30, engine='engine_on', ready=1, km=101, soc=79)
        for seconds in range(120, 721, 60):
            observe(seconds, km=110, soc=78)
        observe(780, observed=800, code='charging', dc_lid=1, km=110, soc=78)
        observe(840, km=110, soc=79)
        observe(1200, observed=1225, code='charging', dc_lid=1, km=110, soc=81)
        with monitor.tracks.connect() as db:
            legacy = {'start_time':BASE+86400000,'end_time':BASE+86520000,'duration_seconds':120,
                      'distance_km':1,'start_soc':80,'end_soc':79,'partial':True}
            db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                       ('legacy-trip',app.vehicle_key,'trip_end',json.dumps(legacy),'PRIVATE',legacy['end_time']))
        server = make_server(app, 0)
        print(server.server_port, flush=True)
        try:
            server.serve_forever()
        finally:
            app.close()
            server.server_close()
