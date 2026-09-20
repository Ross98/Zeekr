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
    app.trip_cards.clock=lambda:calendar_now+12*3600000


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


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo',action='store_true',help='Preload synthetic bills, tags, tasks and an experiment.')
    parser.add_argument('--partial-charge',action='store_true',help='Use a partial charge for observed-metric acceptance.')
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
        seed_charge_curves(app)
        if args.demo:
            seed_demo(app,session)
        server = make_server(app, args.port)
        print(server.server_port, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            app.close()
