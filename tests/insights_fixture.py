"""Synthetic history fixture. Never opens the owner's session or calls a vehicle."""
import hashlib
import argparse
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zeekr_control.storage import save
from zeekr_control.snapshots import session_scope
from zeekr_control.tracks import day_bounds
from zeekr_control.web import App, make_server
from zeekr_control.monitor import Monitor
from zeekr_control.personal_store import account_scope


def seed(app, session):
    vehicle = hashlib.sha256(b'insights-fixture-car').hexdigest()
    save(app.session_path.parent / 'monitor-binding.json', {'vehicle_key': vehicle})
    app._sync_session(session)
    app.profile = {'name': '合成研究车', 'variant': '离线测试', 'image': '', 'image_alt': '', 'battery_capacity_kwh': 86}
    start, _ = day_bounds('2026-09-20')
    for index in range(125):
        stamp = start + index * 60000
        safety = {'centralLockingStatus': 2, 'trunkOpenStatus': 0}
        climate = {'interiorTemp': round(24 + index / 100, 2), 'temperatureUpdateTime': stamp}
        for side in ('Driver', 'Passenger', 'DriverRear', 'PassengerRear'):
            safety['doorOpenStatus' + side] = 0
            safety['doorLockStatus' + side] = 1
            climate['winPos' + side] = 0
        raw = {'updateTime': stamp, 'vin': 'NEVER-EXPORT-IDENTITY',
               'position': {'latitude': 111600000, 'longitude': 435600000},
               'additionalVehicleStatus': {'electricVehicleStatus': {'chargeLevel': 70 - index / 100,
                   'distanceToEmptyOnBatteryOnly': 300, 'chargeSts': 0, 'chargerState': 0,
                   'statusOfChargerConnection': 0}, 'climateStatus': climate,
                   'maintenanceStatus': {'odometer': 12560}, 'drivingSafetyStatus': safety},
               'temStatus': {'swVersion': '<img src=x onerror=alert(1)>'}}
        app.snapshot_store.publish(session_scope(session), vehicle, raw, stamp, source='monitor')

    # Same vehicle timestamp and payload, genuinely later read.
    app.snapshot_store.publish(session_scope(session), vehicle, raw, stamp + 60000, source='monitor')
    # Historical overnight parking, followed by an incomplete stale-cache fragment.
    night, _ = day_bounds('2026-09-18')
    for minute in range(22*60, 31*60+6, 5):
        driving = minute in (22*60, 31*60+5)
        stamp = night + minute*60000
        raw = {'updateTime': stamp,
               'basicVehicleStatus': {'engineStatus': 'engine_on' if driving else 'engine_off',
                                      'speedValidity': True, 'speed': 20 if driving else 0},
               'additionalVehicleStatus': {
                   'electricVehicleStatus': {'ptReady': 1 if driving else 0,
                       'chargeLevel': round(70 - (minute-22*60)/540, 3),
                       'chargeSts': 0, 'chargerState': 0, 'statusOfChargerConnection': 0},
                   'maintenanceStatus': {'odometer': 1000},
                   'climateStatus': {'interiorTemp': 24}}}
        app.snapshot_store.publish(session_scope(session), vehicle, raw, stamp, source='monitor')


def seed_events(app, partial_charge=False):
    vehicle = hashlib.sha256(b'insights-fixture-car').hexdigest()
    entries = [('report-trip','2026-09-15','trip_end',40,False,70,60),
               ('report-partial','2026-09-16','trip_end',7,True,70,69),
               ('report-charge','2026-09-19','charge_end',0,False,40,80),
               ('report-trip-night','2026-09-20','trip_end',20,False,80,75),
               ('report-previous','2026-08-15','trip_end',30,False,70,60)]
    with Monitor(app.database_path).tracks.connect() as db:
        for identity,date,kind,distance,partial,a,b in entries:
            day,_=day_bounds(date)
            start,end=(day-1800000,day+1800000) if identity.endswith('night') else (day+8*3600000,day+9*3600000)
            summary={'start_time':start,'end_time':end,'duration_seconds':3600,'distance_km':distance,
                     'start_soc':a,'end_soc':b,'soc_delta':b-a,'partial':partial or (partial_charge and identity=='report-charge'),'battery_capacity_kwh':86,
                     'address':'PRIVATE-ADDRESS','vin':'NEVER-EXPORT-IDENTITY'}
            if identity=='report-charge':
                summary['report_v2']={'start':{'charging_mode':'ac'}}
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                       (identity,vehicle,kind,json.dumps(summary),'PRIVATE-MESSAGE',end+600000))
    fixed_now,_=day_bounds('2026-10-05')
    app.usage_reports.clock=lambda:fixed_now
    if partial_charge:
        statistics=app.charging_analytics.statistics
        app.charging_analytics.statistics=lambda vehicle,days=7,mode='all',now=None:statistics(vehicle,days,mode,fixed_now)
    calendar_now,_=day_bounds('2026-09-20')
    app.usage_calendar.clock=lambda:calendar_now+12*3600000
    app.vehicle_life.clock=lambda:calendar_now+12*3600000
    app.data_quality.clock=lambda:calendar_now+12*3600000


def seed_charging_intervals(app, session):
    """Closed, cross-month and late-start intervals in the temporary fixture only."""
    vehicle=hashlib.sha256(b'insights-fixture-car').hexdigest()
    for identity,date,a,b,km,partial in [('interval-a','2026-08-31',30,80,1000,False),
                                       ('interval-b','2026-09-02',40,90,1200,False),
                                       ('interval-c','2026-09-10',80,90,1300,False),
                                       ('interval-late','2026-09-11',80,90,1310,True)]:
        start=day_bounds(date)[0]+8*3600000;end=start+3600000
        report=dict(start=dict(state_time=start,observed_at=start+1000,soc=a,odometer=km,charging=True,charging_mode='dc'),
                    end=dict(state_time=end,observed_at=end+1000,soc=b,odometer=km,charging=False,charging_mode='dc'),
                    partial=partial,profile_snapshot=dict(battery_capacity_kwh=86),quality={})
        body=dict(start_time=start,end_time=end,duration_seconds=3600,start_soc=a,end_soc=b,soc_delta=b-a,partial=partial,report_v2=report)
        with Monitor(app.database_path).tracks.connect() as db:
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                       (identity,vehicle,'charge_end',json.dumps(body),'SYNTHETIC',end))
    stamp=day_bounds('2026-09-11')[0]+8*3600000-60000
    payload=dict(state_time=stamp,observed_at=stamp+1000,soc=80,odometer=1310,charging=False,decoder_version='synthetic-v1')
    with Monitor(app.database_path).tracks.connect() as db:
        db.execute('INSERT INTO report_observations VALUES (?,?,?,?,?)',(vehicle,stamp,stamp+1000,json.dumps(payload),'synthetic-v1'))
    owner=account_scope(session)
    for revision,(identity,date,amount) in enumerate([('interval-a','2026-08-31','40'),('interval-b','2026-09-02','0')]):
        app.charge_ledger.update(owner,vehicle,dict(action='save',revision=revision,date=date,event_id=identity,source='unknown',amount=amount,metered_kwh='40'))


def seed_charging_places(app,session):
    """Charge-location acceptance data; all points and station suggestions are synthetic."""
    vehicle=hashlib.sha256(b'insights-fixture-car').hexdigest();owner=account_scope(session)
    store=app.personal_store
    store.change(owner,vehicle,'place_names','save','synthetic_plaza',dict(name='测试广场',latitude=31.2,longitude=121.4,radius_m=150,shape='circle'),0)
    with Monitor(app.database_path).tracks.connect() as db:
        for identity,date in [('place-repeat','2026-09-10'),('place-old','2026-08-10'),('place-unknown','2026-09-25')]:
            start=day_bounds(date)[0]+8*3600000
            summary=dict(start_time=start,end_time=start+3600000,duration_seconds=3600,start_soc=30,end_soc=80,soc_delta=50,partial=False,battery_capacity_kwh=86,report_v2=dict(start=dict(charging_mode='dc'),end=dict(charging_mode='dc')))
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',(identity,vehicle,'charge_end',json.dumps(summary),'SYNTHETIC',start+3600000))
        for identity,date in [('report-charge','2026-09-19'),('place-repeat','2026-09-10'),('place-old','2026-08-10')]:
            start=day_bounds(date)[0]+8*3600000
            for i in range(6):
                stamp=start+i*300000;lat=32 if i==0 and identity=='report-charge' else 31.2+i/1000000
                loc=dict(valid=True,trusted=True,plottable=True,coordinate_system='WGS84（社区解释）',latitude=lat,longitude=121.4)
                db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',(vehicle,identity+str(i),stamp,stamp+1000,1,json.dumps(loc)))
    revision=store.read(owner,vehicle,'charges')['revision']
    app.charge_ledger.update(owner,vehicle,dict(action='save',revision=revision,event_id='place-repeat',date='2026-09-10',source='unknown',amount='60',metered_kwh='40'))
    app.location_geocoder.charging_candidates=lambda location:[dict(id='synthetic-one',name='测试快充站',distance_m=35),dict(id='synthetic-two',name='测试地下充电站',distance_m=80)]


def seed_reminders(app,session):
    owner=account_scope(session);vehicle=hashlib.sha256(b'insights-fixture-car').hexdigest()
    app.reminders.update(owner,vehicle,dict(action='save',revision=0,name='合成演示：低电量',
        kind='low_soc',threshold=25,confirm_seconds=60,cooldown_minutes=60,enabled=True,
        delivery='in_app',recovery=True))
    start,_=day_bounds('2026-09-20')
    for offset,soc in ((0,20),(60000,20),(120000,40),(180000,40)):
        app.reminders.observe(owner,vehicle,{'updateTime':start+offset,
            'additionalVehicleStatus':{'electricVehicleStatus':{'chargeLevel':soc}}},start+offset)


def seed_charge_curves(app):
    from test_charge_comparison import add_curve,curve_point
    vehicle=hashlib.sha256(b'insights-fixture-car').hexdigest();start,_=day_bounds('2026-07-12')
    for identity,offset,mode,socs in [('curve-a',0,'dc',[20,30,30,40,50,60,70,80]),
                                     ('curve-b',86400000,'ac',[30,40,50,60,70,80,90]),
                                     ('curve-gap',2*86400000,'dc',[30,40,50,60,70,80])]:
        points=[]
        for i,soc in enumerate(socs):
            stamp=start+offset+i*120000+(600000 if identity=='curve-gap' and i>=3 else 0)
            row=curve_point(stamp,soc,7 if mode=='ac' else 120-i*8,mode)
            row['outside_temp']['value']=18+i/2;row['inside_temp']['value']=24+i/3
            if identity=='curve-gap' and i==1:row['outside_temp']['validity']='stale'
            points.append(row)
        add_curve(app.database_path,identity,vehicle,points)


def seed_demo(app,session):
    """Optional review examples; all writes stay in the temporary fixture."""
    owner=account_scope(session);vehicle=hashlib.sha256(b'insights-fixture-car').hexdigest()
    app.charge_ledger.update(owner,vehicle,dict(action='save',revision=0,date='2026-09-19',
        event_id='report-charge',source='home',amount='30.10',metered_kwh='40',unit_price='.75',
        service_fee='0',note='合成家充账单，金额与计量电量均为演示值。'))
    for revision,(event_id,tags) in enumerate([
            ('report-trip',['通勤','接娃']),('report-trip-night',['通勤']),('report-partial',['短途'])]):
        app.trip_tags.update(owner,vehicle,dict(action='save',revision=revision,event_id=event_id,
            tags=tags,note='合成行程标签'))
    for revision,(title,category,amount,date) in enumerate([
            ('周末洗车','洗车','35.00','2026-09-19'),('商场停车','停车','12.00','2026-09-20'),
            ('年度车险','保险','3600.00','2026-09-01')]):
        app.vehicle_life.update(owner,vehicle,dict(action='save',collection='expenses',revision=revision,
            title=title,category=category,amount=amount,date=date,note='合成支出，仅供体验'))
    for revision,(title,date,km) in enumerate([
            ('检查轮胎气压','2026-09-20',None),('下次保养','2026-10-15','20000')]):
        app.vehicle_life.update(owner,vehicle,dict(action='save',collection='reminders',revision=revision,
            title=title,due_date=date,due_km=km,note='合成待办，不发送通知'))
    scope=session_scope(session);timeline=app.archive_reader.timeline(scope,vehicle,'2026-09-20')
    start,_=day_bounds('2026-09-20')
    app.experiments.update(owner,vehicle,dict(action='save',revision=0,title='静置前后读数变化',
        action_text='记录两次合成样本之间的状态变化',action_at=start+30000,
        before=timeline['items'][0]['key'],after=timeline['items'][1]['key'],
        paths=['additionalVehicleStatus.electricVehicleStatus.chargeLevel'],
        note='演示如何保留研究线索；不能据此确认字段语义。'),scope)


def seed_automatic(app, session):
    """Optional analysis examples; never run a monitor or call a cloud client."""
    import time
    from zeekr_control.usage_reports import DAY, date_label
    now = int(time.time()*1000)
    today, _ = day_bounds(date_label(now))
    vehicle = hashlib.sha256(b'insights-fixture-car').hexdigest()
    with Monitor(app.database_path).tracks.connect() as db:
        for index in range(18):
            kind = 'trip_end' if index < 8 else 'charge_end'
            start = today-(12 if index < 5 else 1)*DAY + index*60000
            a, b = (70, 60) if kind == 'trip_end' else (20+(index%5)*5, 80)
            summary = dict(start_time=start, end_time=start+3600000, duration_seconds=3600,
                distance_km=40 if index < 5 else 35, start_soc=a, end_soc=b, soc_delta=b-a,
                partial=index in (5, 8), battery_capacity_kwh=86,
                report_v2={'start': {'charging_mode': 'ac' if index < 13 else 'dc'}})
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                ('auto-demo-%d'%index, vehicle, kind, json.dumps(summary), 'SYNTHETIC', start+3600000))
    report = app.automatic_analyzer.build(session_scope(session), vehicle, now)
    app.automatic_cache.success(session_scope(session), vehicle, now, report)


def seed_place_tag_rules(app, session):
    """Real private-store and timeline inputs for the place-rule browser regression."""
    owner=account_scope(session);vehicle=hashlib.sha256(b'insights-fixture-car').hexdigest()
    app.personal_store.change(owner,vehicle,'place_names','save','rule_test_station',
        dict(name='合成充电站',shape='circle',latitude=31.21,longitude=121.41,radius_m=150),0)
    day,_=day_bounds('2026-09-22')
    rows=[('rules-arrival',day+18*3600000+10*60000,day+18*3600000+38*60000,'trip_end',(31.2,121.4),(31.21,121.41)),
          ('rules-departure',day+19*3600000+20*60000,day+19*3600000+48*60000,'trip_end',(31.21,121.41),(31.2,121.4)),
          ('rules-charge',day+18*3600000+42*60000,day+19*3600000+10*60000,'charge_end',None,None),
          ('rules-pending',day+86400000+10*3600000+40*60000,day+86400000+11*3600000+12*60000,'trip_end',(31.2,121.4),(31.21,121.41))]
    with Monitor(app.database_path).tracks.connect() as db:
        for identity,start,end,kind,a,b in rows:
            raw=dict(start_time=start,end_time=end,duration_seconds=(end-start)/1000,distance_km=20,
                     start_soc=40 if kind=='charge_end' else 80,end_soc=70 if kind=='charge_end' else 75,
                     soc_delta=30 if kind=='charge_end' else -5,partial=False)
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                       (identity,vehicle,kind,json.dumps(raw),'SYNTHETIC',end))
            if a:
                for suffix,stamp,point in [('a',start+1000,a),('b',end-1000,b)]:
                    location=dict(latitude=point[0],longitude=point[1],trusted=True,plottable=True,coordinate_system='WGS84（社区解释）')
                    db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',
                               (vehicle,identity+suffix,stamp,stamp,0,json.dumps(location)))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo',action='store_true',help='Preload synthetic bills, tags, tasks and an experiment.')
    parser.add_argument('--partial-charge',action='store_true',help='Use a partial charge for observed-metric acceptance.')
    parser.add_argument('--automatic',action='store_true',help='Preload synthetic automatic analysis results.')
    parser.add_argument('--charging-intervals',action='store_true',help='Preload synthetic interval boundaries.')
    parser.add_argument('--charging-places',action='store_true',help='Preload synthetic charging venues and station candidates.')
    parser.add_argument('--place-tag-rules',action='store_true',help='Seed synthetic place rule timelines.')
    parser.add_argument('--report-now',help='Fixed report-only Beijing date for deterministic current-period assertions.')
    parser.add_argument('--port',type=int,default=0,help='Loopback port; default chooses an available port.')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        session_path = Path(directory) / 'private' / 'session.json'
        session = {'accessToken': 'SYNTHETIC-ONLY'}
        save(session_path, session)
        def forbidden(_):
            raise AssertionError('Cloud client is forbidden in the history fixture')
        app = App(session_path, client_factory=forbidden)
        seed(app, session)
        seed_events(app,args.partial_charge)
        seed_reminders(app,session)
        if args.place_tag_rules:
            seed_place_tag_rules(app,session)
        if args.charging_intervals:
            seed_charging_intervals(app,session)
        seed_charge_curves(app)
        if args.demo:
            seed_demo(app,session)
        if args.charging_places:
            seed_charging_places(app,session)
        if args.automatic:
            seed_automatic(app,session)
        if args.report_now:
            fixed_report_now,_=day_bounds(args.report_now)
            query=app.usage_reports.query
            # The web read context supplies now explicitly; setting only the
            # module clock cannot freeze this real HTTP/analysis path.
            app.usage_reports.query=lambda scope,vehicle,period,date,now=None:query(scope,vehicle,period,date,now=fixed_report_now)
        server = make_server(app, args.port)
        print(server.server_port, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            app.close()
