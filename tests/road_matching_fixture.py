"""Local server for synthetic road-map integration; all telemetry is a fixture."""
import json
from pathlib import Path
import tempfile
from web_fixture import FixtureClient
from zeekr_control.storage import save
from zeekr_control.web import App,make_server
from zeekr_control.monitor import Monitor
from zeekr_control.road_network import build_network
from test_road_matching import osm

with tempfile.TemporaryDirectory() as directory:
    session=Path(directory)/'private'/'session.json'
    save(session,{'accessToken':'TEST-ONLY','userId':'TEST-ONLY'})
    app=App(session,client_factory=FixtureClient);app.refresh(1)
    build_network(osm(),session.parent/'road-networks'/'synthetic.sqlite3')
    store=Monitor(app.database_path).tracks
    base=1704160800000
    coords=[(121.0001,31),(121.0007,31),(121.001,31.0007),(121.001,31.0008),(121.001,31.0009)]
    times=[0,60,120,360,420]
    for (lon,lat),seconds in zip(coords,times):
        timestamp=base+seconds*1000
        store.record(app.vehicle_key,{'updateTime':timestamp,'position':{'latitude':round(lat*3600000),
            'longitude':round(lon*3600000),'marsCoordinates':False,'posCanBeTrusted':True}},timestamp+1000,180)
    event={'start_time':base,'end_time':base+420000,'duration_seconds':420,'distance_km':.2,
           'start_soc':70,'end_soc':70,'partial':False,'battery_capacity_kwh':86}
    with store.connect() as db:
        db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
            ('road-trip',app.vehicle_key,'trip_end',json.dumps(event),'SYNTHETIC',base+420000))
    server=make_server(app,0);print(server.server_port,flush=True)
    try:server.serve_forever()
    finally:app.close();server.server_close()
