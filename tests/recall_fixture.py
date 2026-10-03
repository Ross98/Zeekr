"""Daily recall demo and repeatable benchmark; synthetic local data only."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from insights_fixture import seed
from zeekr_control.storage import save
from zeekr_control.snapshots import session_scope
from zeekr_control.web import App,make_server
from zeekr_control.monitor import Monitor
from zeekr_control.tracks import day_bounds


def populate(app,session,performance=False):
    seed(app,session)
    car=hashlib.sha256(b'insights-fixture-car').hexdigest()
    start,_=day_bounds('2026-09-20')
    tracks=Monitor(app.database_path).tracks
    events=[('recall-drive',start+8*3600000,1200,'trip_end',12),
            ('recall-charge',start+9*3600000,1800,'charge_end',None),
            ('recall-return',start+10*3600000,1200,'trip_end',15)]
    if performance:
        events.extend((f'history-{i}',start-((i%19)+1)*86400000+13*3600000+(i//19)*3600000,300,'trip_end',2) for i in range(60))
        events.extend((f'dense-{i}',start+8*3600000+i*30000,15,'trip_end',1) for i in range(120))
        first,_=day_bounds('2024-01-01')
        events.extend((f'perf-{i}',first+i*86400000+8*3600000,300,'trip_end',10) for i in range(366))
    with tracks.connect() as db:
        for identity,begin,seconds,kind,distance in events:
            summary=dict(start_time=begin,end_time=begin+seconds*1000,duration_seconds=seconds,distance_km=distance,
                         start_soc=40 if kind=='charge_end' else 80,end_soc=80 if kind=='charge_end' else 75,
                         soc_delta=40 if kind=='charge_end' else -5,partial=False,battery_capacity_kwh=86,
                         start_address='合成园区',end_address='合成停车场',
                         start_location=dict(latitude=31.2,longitude=121.4,valid=True,trusted=True,coordinate_system='WGS84（社区解释）'),
                         end_location=dict(latitude=31.21,longitude=121.41,valid=True,trusted=True,coordinate_system='WGS84（社区解释）'))
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                       (identity,car,kind,json.dumps(summary),'SYNTHETIC',summary['end_time']))
    if performance:
        for identity,begin,seconds,kind,distance in events:
            if not identity.startswith('history-'):continue
            for stamp,lat,lon in [(begin+30000,31.2,121.4),(begin+seconds*1000-30000,31.21,121.41)]:
                tracks.record(car,{'updateTime':stamp,'position':{'latitude':round(lat*3600000),'longitude':round(lon*3600000),'posCanBeTrusted':True,'marsCoordinates':False}},stamp,180)
    for minute in range(8*60,11*60+1):
        stamp=start+minute*60000
        moving=minute<8*60+20 or 10*60<=minute<10*60+20 or minute==11*60
        charging=9*60<=minute<9*60+30
        lat=31.2+(minute-480)/180*.01 if moving else 31.21
        lon=121.4+(minute-480)/180*.01 if moving else 121.41
        raw={'updateTime':stamp,'position':{'latitude':round(lat*3600000),'longitude':round(lon*3600000),'posCanBeTrusted':True,'marsCoordinates':False},
             'basicVehicleStatus':{'engineStatus':'engine_on' if moving else 'engine_off','speedValidity':True,'speed':20 if moving else 0},
             'additionalVehicleStatus':{'electricVehicleStatus':{'ptReady':1 if moving else 0,'chargeLevel':70,'chargeSts':1 if charging else 0,'chargerState':1 if charging else 0,'statusOfChargerConnection':1 if charging else 0},'maintenanceStatus':{'odometer':1000}}}
        app.snapshot_store.publish(session_scope(session),car,raw,stamp,source='monitor')
        tracks.record(car,raw,stamp,180)
    if performance:
        begin=start+8*3600000
        for i in range(4000):
            stamp=begin+i*1000
            tracks.record(car,{'updateTime':stamp,'position':{'latitude':111600000+i*30,'longitude':435600000+i*40,'posCanBeTrusted':True,'marsCoordinates':False}},stamp,180)
        # September history: one observed stationary interval per day.
        for day in range(1,20):
            begin,_=day_bounds(f'2026-09-{day:02d}')
            for minute in range(30):
                stamp=begin+(8*60+minute)*60000
                raw={'updateTime':stamp,'position':{'latitude':111600000,'longitude':435600000,'posCanBeTrusted':True,'marsCoordinates':False},'basicVehicleStatus':{'engineStatus':'engine_off','speedValidity':True,'speed':0},'additionalVehicleStatus':{'electricVehicleStatus':{'ptReady':0,'chargeLevel':70,'chargeSts':0,'chargerState':0}}}
                app.snapshot_store.publish(session_scope(session),car,raw,stamp,source='monitor');tracks.record(car,raw,stamp,180)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--performance',action='store_true');parser.add_argument('--port',type=int,default=0);args=parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'private'/'session.json';session={'accessToken':'SYNTHETIC-ONLY','userId':'recall-demo'};save(path,session)
        def forbidden(_):raise AssertionError('Vehicle gateway forbidden')
        app=App(path,client_factory=forbidden);populate(app,session,args.performance)
        server=make_server(app,args.port);print(server.server_port,flush=True)
        try:server.serve_forever()
        finally:server.server_close();app.close()
