import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from zeekr_control.storage import save, load
from test_monitor import BASE, sample


class RuntimeTests(unittest.TestCase):
    def test_tyre_reminders_use_existing_observations_and_independent_senders(self):
        class Client:
            seconds=0;calls=0
            def __init__(self,session):pass
            def vehicles(self):return [{'vin':'L6T79X2Z0NP000001'}]
            def status(self,vin):
                Client.calls+=1
                raw=sample(Client.seconds)
                raw['additionalVehicleStatus']['maintenanceStatus']['tyreStatusDriver']=200
                return raw
        runner=self.runner(Client);bark=[];wecom=[]
        runner.alert_sender=lambda *args:bark.append(args);runner.sender=wecom.append
        runner.tick(BASE);Client.seconds=20;runner.tick(BASE+20000)
        self.assertEqual(Client.calls,2)
        self.assertEqual((len(bark),len(wecom)),(0,0))
        self.deliver(runner,BASE+20000)
        self.assertEqual((len(bark),len(wecom)),(1,1))
        self.assertIn('胎压明显偏低',bark[0][0]);self.assertIn('软件参考提醒',wecom[0])

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('zeekr_control.monitor_runtime'), '后台监控尚未实现')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private'
        save(self.root / 'session.json', {'accessToken': 'synthetic'})

    def deliver(self,runner,now):
        with patch('zeekr_control.delivery_runtime.StorageHealth.tick'):
            runner.deliver_once(now)

    def runner(self, client):
        from zeekr_control.monitor_runtime import Runner
        return Runner(self.root / 'session.json', client_factory=client, sender=lambda message: None)

    def test_place_tags_are_collected_without_a_web_query(self):
        import hashlib
        import sqlite3
        from zeekr_control.personal_store import account_scope
        class Client:
            def __init__(self,session):pass
            def vehicles(self):return [{'vin':'L6T79X2Z0NP000001'}]
            def status(self,vin):return sample(0)
        runner=self.runner(Client);self.addCleanup(runner.insight_worker.close)
        runner.tick(BASE)
        owner=account_scope({'accessToken':'synthetic'})
        vehicle=hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest()
        engine=runner.place_tag_rules;store=engine.store
        store.change(owner,vehicle,'place_names','save','runtime_station',dict(name='合成站点',latitude=31.21,longitude=121.41,radius_m=150),0)
        from datetime import datetime,timezone
        date=datetime.fromtimestamp(BASE/1000,timezone.utc).strftime('%Y-%m-%d')
        body=dict(action='place-rule-preview',date=date,revision=0,region_id='runtime_station',tag='充电',direction='arrive',require_charge=False,enabled=True)
        with patch('zeekr_control.place_tag_rules.time.time',return_value=BASE/1000):
            preview=engine.update(owner,vehicle,body)
            engine.update(owner,vehicle,dict(body,action='place-rule-save',preview_token=preview['token']))
        start,end=BASE+1000,BASE+121000
        with sqlite3.connect(self.root/'tracks.sqlite3') as db:
            encoded=json.dumps(dict(start_time=start,end_time=end,duration_seconds=120,distance_km=2,start_soc=80,end_soc=79,partial=False))
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',('runtime-arrival',vehicle,'trip_end',encoded,'',end))
            for stamp,lat,lon in [(start+1000,31.2,121.4),(end-1000,31.21,121.41)]:
                location=json.dumps(dict(latitude=lat,longitude=lon,trusted=True,plottable=True,coordinate_system='WGS84（社区解释）'))
                db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',(vehicle,'runtime-'+str(stamp),stamp,stamp,30,location))
        runner.tick(BASE+180000)
        with store.connect() as db:
            row=db.execute('SELECT body FROM place_tag_decisions WHERE owner=? AND vehicle=? AND event_id=?',(owner,vehicle,'runtime-arrival')).fetchone()
        self.assertIsNotNone(row);self.assertEqual(json.loads(row[0])['result'],'matched')

    def test_runner_uses_private_offline_networks_for_focused_trip_images(self):
        from zeekr_control.monitor_runtime import Runner
        from zeekr_control.focused_trip_image import FocusedTripImage
        runner = Runner(self.root / 'session.json', client_factory=lambda session: None,
                        sender=lambda message: None)
        self.addCleanup(lambda: runner.insight_worker.close())
        self.assertIsInstance(runner.monitor.map_renderer, FocusedTripImage)
        self.assertEqual(runner.monitor.map_renderer.network_dir, self.root / 'road-networks')

    def test_binding_follows_vehicle_identity_not_list_order(self):
        class Client:
            order = ['L6T79X2Z0NP000001']
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': v} for v in self.order]
            def status(self, vin):
                if vin != 'L6T79X2Z0NP000001': raise AssertionError('wrong vehicle')
                return sample(0)
        runner = self.runner(Client)
        runner.tick(BASE)
        Client.order = ['L6T79X2Z0NP000002', 'L6T79X2Z0NP000001']
        runner = self.runner(Client)
        runner.tick(BASE + 1000)
        self.assertEqual(runner.health()['status'], 'unchanged')
        Client.order = ['L6T79X2Z0NP000002']
        runner.tick(BASE + 2000)
        self.assertEqual(runner.health()['status'], 'blocked')

    def test_old_parked_repeat_is_waiting_but_other_old_states_stay_stale(self):
        class Client:
            raw = sample(0)
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin): return Client.raw
        runner = self.runner(Client)
        runner.tick(BASE)
        runner.tick(BASE + 24 * 3600000)
        health = runner.health()
        self.assertEqual(health['status'], 'parked_waiting')
        self.assertEqual(health['data_change'], 'repeat')
        self.assertEqual(health['state_time'], str(BASE))
        self.assertEqual(health['last_success'], str(BASE + 24 * 3600000))
        self.assertEqual(health['error'], '')
        self.assertEqual(runner.monitor.status(__import__('hashlib').sha256(b'L6T79X2Z0NP000001').hexdigest())['last']['time'], BASE)
        Client.raw = sample(0, soc=79)
        runner.tick(BASE + 24 * 3600000 + 20000)
        self.assertEqual(runner.health()['data_change'], 'revision')
        self.assertEqual(runner.health()['status'], 'stale')
        Client.raw = sample(1, speed=40, engine='engine_running', ready=1)
        runner.tick(BASE + 24 * 3600000 + 40000)
        runner.tick(BASE + 24 * 3600000 + 60000)
        self.assertEqual(runner.health()['status'], 'stale')
        Client.raw = sample(24 * 3600 + 80)
        runner.tick(BASE + 24 * 3600000 + 80000)
        self.assertEqual(runner.health()['data_change'], 'new')
        self.assertEqual(runner.health()['status'], 'fresh')

    def test_old_parked_p_gear_repeat_with_unavailable_speed_waits_for_update(self):
        class Client:
            raw = sample(0)
            raw['basicVehicleStatus']['speedValidity'] = False
            raw['additionalVehicleStatus']['drivingBehaviourStatus'] = {'gearAutoStatus': 0}
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin): return Client.raw
        runner = self.runner(Client)
        runner.tick(BASE)
        runner.tick(BASE + 3600000)
        self.assertEqual(runner.health()['status'], 'parked_waiting')
        self.assertEqual(runner.health()['data_change'], 'repeat')
        self.assertEqual(runner.health()['state_time'], str(BASE))
        Client.raw['additionalVehicleStatus']['drivingBehaviourStatus']['gearAutoStatus'] = 2
        runner.tick(BASE + 3620000)
        runner.tick(BASE + 3640000)
        self.assertEqual(runner.health()['status'], 'stale')

    def test_parking_wait_does_not_mask_failed_reads_or_unknown_and_future_states(self):
        from zeekr_control.errors import ApiError
        class Client:
            raw = sample(0)
            fail = False
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin):
                if Client.fail: raise ApiError('网络或 TLS 连接失败')
                return Client.raw
        runner = self.runner(Client)
        runner.tick(BASE)
        runner.tick(BASE + 3600000)
        self.assertEqual(runner.health()['status'], 'parked_waiting')
        Client.fail = True
        runner.tick(BASE + 3620000)
        self.assertEqual(runner.health()['status'], 'retrying')
        self.assertTrue(runner.health()['error'])
        Client.fail = False
        for label, raw in [('unknown-speed', sample(0)), ('future', sample(10000)),
                           ('unknown-time', sample(0))]:
            with self.subTest(label=label):
                if label == 'unknown-speed': raw['basicVehicleStatus']['speedValidity'] = False
                if label == 'unknown-time': raw.pop('updateTime')
                Client.raw = raw
                runner.tick(BASE + 3640000)
                runner.tick(BASE + 3660000)
                self.assertEqual(runner.health()['status'], 'stale')

    def test_successful_tick_publishes_shared_snapshot(self):
        class Client:
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin): return sample(0)
        runner = self.runner(Client)
        runner.tick(BASE)
        from zeekr_control.snapshots import SnapshotStore, session_scope
        snapshot = SnapshotStore(self.root / 'snapshots.sqlite3').read(
            session_scope({'accessToken': 'synthetic'}),
            __import__('hashlib').sha256(b'L6T79X2Z0NP000001').hexdigest())
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot['raw']['updateTime'], BASE)
        import sqlite3
        archive = list((self.root / 'snapshot-archive').glob('*/*.sqlite3'))
        self.assertEqual(len(archive), 1)
        runner.tick(BASE + 60000)  # Same cached vehicle response, distinct read.
        with sqlite3.connect(archive[0]) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reads').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM payloads').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT DISTINCT source FROM reads').fetchall(), [('monitor',)])

    def test_custom_rules_use_collected_data_without_extra_queries_or_real_sender(self):
        import hashlib
        from zeekr_control.personal_store import account_scope
        class Client:
            tick=0;calls=0
            def __init__(self,session):pass
            def vehicles(self):return [{'vin':'L6T79X2Z0NP000001'}]
            def status(self,vin):
                Client.calls+=1
                return sample(Client.tick,soc=20)
        runner=self.runner(Client);messages=[];runner.sender=messages.append
        owner=account_scope({'accessToken':'synthetic'})
        car=hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest()
        runner.reminders.update(owner,car,dict(action='save',revision=0,name='合成提醒',kind='low_soc',threshold=25,
                confirm_seconds=60,cooldown_minutes=60,enabled=True,delivery='wecom',recovery=True))
        runner.tick(BASE);Client.tick=60;runner.tick(BASE+60000)
        self.assertEqual(Client.calls,2)
        self.assertEqual(len(messages),0)
        self.deliver(runner,BASE+60000)
        self.assertEqual(len(messages),1)
        self.assertEqual(runner.reminders.query(owner,car)['history'][0]['delivery'],'sent')
        restarted=self.runner(Client);restarted.sender=messages.append
        Client.tick=120;restarted.tick(BASE+120000);self.deliver(restarted,BASE+120000)
        self.assertEqual(len(messages),1)

    def test_multiple_vehicles_require_explicit_selection(self):
        class Client:
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}, {'vin': 'L6T79X2Z0NP000002'}]
            def status(self, vin): raise AssertionError('must not query')
        runner = self.runner(Client)
        runner.tick(BASE)
        self.assertEqual(runner.health()['status'], 'blocked')

    def test_successful_collection_schedules_analysis_without_extra_vehicle_query(self):
        from zeekr_control.monitor_runtime import collection_loop
        from zeekr_control.snapshots import session_scope
        import hashlib
        import threading
        class Client:
            calls = 0
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin):
                Client.calls += 1
                return sample(0)
        runner = self.runner(Client)
        self.addCleanup(lambda: runner.insight_worker.close())
        with patch('zeekr_control.monitor_runtime.time.time', return_value=BASE/1000):
            collection_loop(runner, threading.Event(), once=True)
        self.assertEqual(Client.calls, 1)
        self.assertIsNotNone(runner.insight_worker.thread)
        runner.insight_worker.thread.join(2)
        data = runner.insight_worker.cache.query(session_scope({'accessToken': 'synthetic'}),
            hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest(), BASE, 0)
        self.assertEqual(data['status'], 'ready')
        self.assertEqual(data['report']['quality']['reads'], 1)
        save(self.root/'sampling.json', {'enabled': 'false'})
        runner.tick(BASE+3600000)
        self.assertFalse(runner.start_analysis())

    def test_analysis_context_guard_rejects_changed_session_and_pause(self):
        class Client:
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin): return sample(0)
        runner = self.runner(Client)
        runner.tick(BASE)
        with patch.object(runner.insight_worker, 'start', return_value=True) as start:
            self.assertTrue(runner.start_analysis())
            guard = start.call_args.args[3]
            self.assertTrue(guard())
            save(self.root/'sampling.json', {'enabled': 'false'})
            self.assertFalse(guard())
            save(self.root/'sampling.json', {'enabled': 'true'})
            save(self.root/'session.json', {'accessToken': 'different'})
            self.assertFalse(guard())

    def test_credentials_error_waits_for_session_change_without_requery(self):
        from zeekr_control.errors import ApiError
        class Client:
            calls = 0
            def __init__(self, session): pass
            def vehicles(self):
                Client.calls += 1
                raise ApiError('网关 HTTP 401；未自动重试。')
        runner = self.runner(Client)
        runner.tick(BASE)
        runner.tick(BASE + 60000)
        self.assertEqual(Client.calls, 1)
        save(self.root / 'session.json', {'accessToken': 'new-synthetic'})
        runner.tick(BASE + 120000)
        self.assertEqual(Client.calls, 2)

    def test_gateway_1509_retries_durably_and_recovers_without_login(self):
        from zeekr_control.errors import ApiError
        from zeekr_control.monitor_runtime import Runner
        messages = []
        class Client:
            valid = False
            calls = 0
            def __init__(self, session): pass
            def vehicles(self):
                Client.calls += 1
                if not Client.valid:
                    raise ApiError('status 失败，网关代码 1509', gateway_code='1509', gateway_reason='会话暂不可用',
                                   notification_reason='服务维护中，稍后再试。 phone=13800000000')
                return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin): return sample(0)
        def runner():
            value = Runner(self.root/'session.json', client_factory=Client,
                           sender=lambda message: None,
                           alert_sender=lambda title, body: messages.append((title, body)))
            self.addCleanup(value.insight_worker.close)
            return value
        first = runner()
        self.assertEqual(first.tick(BASE), 60)
        self.assertEqual(first.health()['status'], 'retrying')
        self.deliver(first, BASE)
        self.assertEqual(messages, [])
        restarted = runner()
        restarted.tick(BASE + 30000)
        self.assertEqual(Client.calls, 1, 'restart must respect existing retry deadline')
        self.assertEqual(restarted.tick(BASE + 60000), 120)
        self.assertEqual(restarted.tick(BASE + 180000), 240)
        self.assertEqual(restarted.tick(BASE + 420000), 300)
        self.deliver(restarted, BASE + 420000)
        self.assertEqual(messages, [], 'short interruption stays quiet')
        self.assertEqual(restarted.tick(BASE + 900000), 300)
        self.deliver(restarted, BASE + 900000)
        self.assertEqual(len(messages), 1)
        self.assertNotIn('重新登录', messages[0][1])
        self.assertIn('自动重试', messages[0][1])
        self.assertIn('网关说明：服务维护中，稍后再试。 phone=13800000000', messages[0][1])
        self.assertEqual(restarted.health()['gateway_reason'], '会话暂不可用')
        Client.valid = True
        restarted.tick(BASE + 1800000)
        self.assertNotEqual(restarted.health()['status'], 'blocked')
        self.assertEqual(restarted.health()['error'], '')
        self.assertEqual(restarted.health()['last_success'], str(BASE + 1800000))
        self.assertNotIn('gateway_retry', restarted.health())
        with restarted.auth_failure_alert.connect() as db:
            self.assertEqual(db.execute('SELECT active FROM auth_state').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM gateway_failures').fetchone()[0], 5)

    def test_1509_session_change_bypasses_old_backoff_and_pending_alert_is_cancelled(self):
        from zeekr_control.errors import ApiError
        class Client:
            calls=0
            def __init__(self, session): self.session=session
            def vehicles(self):
                Client.calls+=1
                if self.session['accessToken']=='synthetic':
                    raise ApiError('网关代码 1509',gateway_code='1509')
                return [{'vin':'L6T79X2Z0NP000001'}]
            def status(self,vin): return sample(0)
        runner=self.runner(Client);self.addCleanup(runner.insight_worker.close)
        runner.tick(BASE)
        save(self.root/'session.json',{'accessToken':'updated-synthetic'})
        runner.tick(BASE+1000)
        self.assertEqual(Client.calls,2)
        self.assertEqual(runner.health()['error'],'')
        self.assertNotIn('gateway_retry',runner.health())

    def test_1509_audit_is_bounded_and_public_message_keeps_sanitized_reason(self):
        from zeekr_control.monitor_runtime import read_status
        runner=self.runner(lambda session:None);self.addCleanup(runner.insight_worker.close)
        for i in range(205): runner.auth_failure_alert.record_failure('1509','会话暂不可用',BASE+i)
        with runner.auth_failure_alert.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM gateway_failures').fetchone()[0],200)
        save(self.root/'monitor-health.json',{'status':'retrying','heartbeat':str(BASE),'error':'status 失败，网关代码 1509','gateway_reason':'会话暂不可用 phone=13800000000'})
        value=read_status(self.root,public=True)
        self.assertIn('会话暂不可用',value['error'])
        self.assertNotIn('13800000000',str(value))
        self.assertNotIn('重新登录',value['error'])

    def test_short_1509_gap_breaks_track_and_preserves_existing_trip(self):
        from zeekr_control.errors import ApiError
        class Client:
            seconds=0
            fail=False
            def __init__(self,session): pass
            def vehicles(self): return [{'vin':'L6T79X2Z0NP000001'}]
            def status(self,vin):
                if Client.fail: raise ApiError('网关代码 1509',gateway_code='1509')
                return sample(Client.seconds,speed=30 if Client.seconds else 0,
                              engine='engine_on' if Client.seconds else 'engine_off',
                              ready=int(Client.seconds>0),km=100+Client.seconds/10)
        runner=self.runner(Client);self.addCleanup(runner.insight_worker.close)
        runner.tick(BASE)
        Client.seconds=20;runner.tick(BASE+20000)
        Client.fail=True;runner.tick(BASE+40000)
        binding=load(self.root/'monitor-binding.json')['vehicle_key']
        self.assertTrue(runner.monitor.status(binding)['trip']['partial'])
        with runner.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0],2)
        Client.fail=False;Client.seconds=100;runner.tick(BASE+100000)
        with runner.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT gap_seconds FROM observations ORDER BY id DESC LIMIT 1').fetchone()[0],0)
        route=runner.monitor.tracks.day(binding,'2024-01-01')
        self.assertGreaterEqual(route['quality']['gap_count'],1)
        self.assertNotIn('gap_pending',runner.health())
        self.assertEqual(runner.monitor.status(binding)['trip']['start']['km'],100)

    def test_recovery_keeps_driving_scalars_without_gps(self):
        from zeekr_control.errors import ApiError
        class Client:
            seconds=0
            fail=False
            def __init__(self,session): pass
            def vehicles(self): return [{'vin':'L6T79X2Z0NP000001'}]
            def status(self,vin):
                if Client.fail: raise ApiError('网关代码 1509',gateway_code='1509')
                raw=sample(Client.seconds,speed=30 if Client.seconds else 0,
                           engine='engine_on' if Client.seconds else 'engine_off',
                           ready=int(Client.seconds>0),km=100+Client.seconds/10,soc=80-Client.seconds/100)
                raw.pop('position',None)
                return raw
        runner=self.runner(Client);self.addCleanup(runner.insight_worker.close)
        runner.tick(BASE)
        Client.seconds=20;runner.tick(BASE+20000)
        Client.fail=True;runner.tick(BASE+40000)
        Client.fail=False;Client.seconds=100;runner.tick(BASE+100000)
        binding=load(self.root/'monitor-binding.json')['vehicle_key']
        state=runner.monitor.status(binding)
        self.assertEqual(state['last']['km'],110)
        self.assertEqual(state['last']['soc'],79)
        self.assertEqual(state['trip']['start']['km'],100)
        self.assertTrue(state['trip']['partial'])
        with runner.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM report_observations').fetchone()[0],3)
        self.assertEqual(runner.health()['last_success'],str(BASE+100000))

    def test_upgrade_of_stopped_legacy_1509_marks_existing_trip_incomplete(self):
        class Client:
            seconds=0
            def __init__(self,session): pass
            def vehicles(self): return [{'vin':'L6T79X2Z0NP000001'}]
            def status(self,vin): return sample(Client.seconds,speed=30 if Client.seconds else 0,engine='engine_on' if Client.seconds else 'engine_off',ready=int(Client.seconds>0))
        runner=self.runner(Client);self.addCleanup(runner.insight_worker.close)
        runner.tick(BASE);Client.seconds=20;runner.tick(BASE+20000)
        health=runner.health();health.update(status='stopped',error='status 失败，网关代码 1509；请重新登录')
        save(self.root/'monitor-health.json',health)
        Client.seconds=40;runner.tick(BASE+40000)
        binding=load(self.root/'monitor-binding.json')['vehicle_key']
        self.assertTrue(runner.monitor.status(binding)['trip']['partial'])
        self.assertEqual(runner.health()['error'],'')

    def test_refresh_success_waits_for_real_target_status_and_keeps_new_session(self):
        from zeekr_control.client import Client
        from zeekr_control.credential_store import FileCredentialStore
        from zeekr_control.refresh_recovery import RefreshDriver,RefreshPolicy
        from zeekr_control.personal_store import account_scope
        from zeekr_control.monitor_runtime import Runner
        session=dict(accessToken='old-access',refreshToken='old-refresh',userId='user',clientId='client',deviceId='device')
        save(self.root/'session.json',session)
        calls=[];seconds=[0]
        def wire(method,url,headers,body):
            calls.append(method)
            if method=='PUT':return {'code':'1000','data':{'accessToken':'new-access','refreshToken':'new-refresh'}}
            if '/status/' in url:
                if headers['authorization']=='old-access':return {'code':1509,'message':'会话暂不可用'}
                return {'code':'1000','data':sample(seconds[0])}
            return {'code':'1000','data':{'list':[{'vin':'L6T79X2Z0NP000001'}]}}
        factory=lambda session:Client(session,wire)
        driver=RefreshDriver(self.root/'session.json',client_factory=factory,policy=RefreshPolicy(enabled=True),
                             store=FileCredentialStore(self.root/'session.json',allow_refresh=True))
        runner=Runner(self.root/'session.json',client_factory=factory,sender=lambda text:None,refresh_driver=driver)
        self.addCleanup(runner.insight_worker.close)
        for seconds[0] in (0,60,180):runner.tick(BASE+seconds[0]*1000)
        self.assertEqual(calls.count('PUT'),1)
        self.assertEqual(runner.health()['refresh_status'],'refreshed')
        binding=load(self.root/'monitor-binding.json')['vehicle_key']
        incident=runner.incidents.current(account_scope(session),binding)
        self.assertIsNotNone(incident)
        self.assertIsNotNone(incident['refresh_completed_at'])
        seconds[0]=181;runner.tick(BASE+181000)
        self.assertIsNone(runner.incidents.current(account_scope(session),binding))
        self.assertEqual(load(self.root/'session.json')['accessToken'],'new-access')
        self.assertEqual(runner.health()['error'],'')

    def test_incident_storage_failure_does_not_drop_received_driving_data(self):
        import sqlite3
        class Client:
            def __init__(self,session):pass
            def vehicles(self):return [{'vin':'L6T79X2Z0NP000001'}]
            def status(self,vin):return sample(0)
        runner=self.runner(Client);self.addCleanup(runner.insight_worker.close)
        with patch.object(runner.incidents,'success',side_effect=OSError('unavailable')):
            runner.tick(BASE)
        health=load(self.root/'monitor-health.json')
        self.assertEqual(health['last_success'],str(BASE))
        self.assertEqual(health['incident_recording'],'unavailable')
        with sqlite3.connect(self.root/'snapshots.sqlite3') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0],1)

    def test_manual_alert_is_deduplicated_by_incident_and_keeps_uncertain_delivery(self):
        from zeekr_control.system_notifications import AuthFailureAlert
        messages=[]
        alert=AuthFailureAlert(self.root,lambda *message:messages.append(message))
        alert.blocked('网关代码 1509',BASE,manual=True,incident_id='incident-one');alert.deliver()
        alert.recovered()
        alert.blocked('网关代码 1509',BASE+1000,manual=True,incident_id='incident-one');alert.deliver()
        self.assertEqual(len(messages),1)
        alert.blocked('网关代码 1509',BASE+2000,manual=True,incident_id='incident-two');alert.deliver()
        self.assertEqual(len(messages),2)
        self.assertIn('不会自动重放',messages[0][1])

    def test_auth_alert_does_not_send_on_other_blocked_errors(self):
        from zeekr_control.errors import ApiError
        from zeekr_control.monitor_runtime import Runner
        messages = []
        class Client:
            def __init__(self, session): pass
            def vehicles(self): raise ApiError('原绑定车辆不在当前车辆列表中')
        runner = Runner(self.root/'session.json', client_factory=Client,
                        sender=lambda message: None,
                        alert_sender=lambda title, body: messages.append((title, body)))
        self.addCleanup(runner.insight_worker.close)
        runner.tick(BASE)
        self.assertEqual(messages, [])

    def test_auth_alert_uncertain_delivery_is_not_repeated(self):
        from zeekr_control.monitor_runtime import AuthFailureAlert
        from zeekr_control.notifications import DeliveryError
        calls = []
        def uncertain(title, body):
            calls.append((title, body))
            raise DeliveryError('timeout', ambiguous=True)
        alert = AuthFailureAlert(self.root, uncertain)
        alert.blocked('status 失败，网关代码 1509');alert.deliver()
        restarted=AuthFailureAlert(self.root,uncertain)
        restarted.blocked('status 失败，网关代码 1509');restarted.deliver()
        self.assertEqual(len(calls), 1)
        with alert.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM auth_outbox').fetchone()[0],'uncertain')

    def test_process_lock_rejects_second_monitor(self):
        from zeekr_control.monitor_runtime import process_lock
        with process_lock(self.root / 'monitor.lock'):
            with self.assertRaisesRegex(ValueError, '运行'):
                with process_lock(self.root / 'monitor.lock'):
                    self.fail('second monitor started')

    def test_cli_accepts_monitor_and_status_commands(self):
        from zeekr_control.cli import parser
        args = parser().parse_args(['monitor', '--once'])
        self.assertTrue(args.once)
        args = parser().parse_args(['monitor-status'])
        self.assertEqual(args.command, 'monitor-status')

    def test_public_status_filters_vehicle_and_never_returns_private_summary(self):
        import sqlite3
        from zeekr_control.monitor import Monitor
        from zeekr_control.monitor_runtime import read_status
        Monitor(self.root / 'tracks.sqlite3')
        with sqlite3.connect(self.root / 'tracks.sqlite3') as db:
            for vehicle in ('car-a','car-b'):
                db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                    (vehicle,vehicle,'trip_end',json.dumps({'report_v2':{'secret':'PRIVATE'},'start_location':[1,2]}),'PRIVATE',1))
                db.execute('INSERT INTO monitor_event_alerts(event_id) VALUES(?)', (vehicle,))
        save(self.root/'monitor-health.json', {'status':'fresh','heartbeat':str(BASE),'next_check':str(BASE+60000),
             'signals':'PRIVATE-SIGNALS','raw_future':'PRIVATE-FUTURE'})
        result = read_status(self.root,'car-a',public=True)
        encoded = json.dumps(result)
        self.assertEqual(len(result['events']),1)
        self.assertNotIn('summary',result['events'][0])
        self.assertNotIn('PRIVATE',encoded)
        self.assertNotIn('signals',result)
        self.assertEqual(result['events'][0]['alert_delivery'], 'pending')
        self.assertEqual(read_status(self.root,None,public=True)['events'],[])


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'private' / 'webhook.json'
        save(self.path, {'webhook_url': 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=synthetic-key-for-tests'})

    def test_success_sends_utf8_text_and_rejects_provider_failure(self):
        from zeekr_control.notifications import WeComSender, DeliveryError
        import io
        class Opener:
            code = 0
            def open(self, request, timeout):
                payload = json.loads(request.data)
                if payload != {'msgtype': 'text', 'text': {'content': '测试'}}:
                    raise AssertionError('wrong message payload')
                return io.BytesIO(json.dumps({'errcode': self.code}).encode())
        opener = Opener()
        with patch('zeekr_control.notifications.build_opener', return_value=opener):
            WeComSender(self.path)('测试')
            opener.code = 45009
            with self.assertRaises(DeliveryError) as caught:
                WeComSender(self.path)('测试')
            self.assertFalse(caught.exception.ambiguous)
            self.assertFalse(caught.exception.permanent)

    def test_unsafe_url_is_rejected_before_network(self):
        from zeekr_control.notifications import WeComSender, DeliveryError
        save(self.path, {'webhook_url': 'https://evil.invalid/?key=DO-NOT-EXPOSE'})
        with self.assertRaises(DeliveryError) as caught:
            WeComSender(self.path)('测试')
        self.assertNotIn('DO-NOT-EXPOSE', str(caught.exception))
        self.assertTrue(caught.exception.permanent)

    def test_transport_error_is_ambiguous_and_secret_is_not_logged(self):
        from zeekr_control.notifications import WeComSender, DeliveryError
        with patch('zeekr_control.notifications.build_opener') as factory:
            factory.return_value.open.side_effect = URLError('SECRET-IN-URL')
            with self.assertRaises(DeliveryError) as caught:
                WeComSender(self.path)('测试')
        self.assertTrue(caught.exception.ambiguous)
        self.assertNotIn('SECRET', str(caught.exception))

    def test_utf8_hard_limit_allows_2048_and_rejects_2049(self):
        import io
        class Opener:
            def open(self, request, timeout): return io.BytesIO(b'{"errcode":0}')
        from zeekr_control.notifications import WeComSender, DeliveryError
        with patch('zeekr_control.notifications.build_opener', return_value=Opener()):
            WeComSender(self.path)('a'*2047)
            WeComSender(self.path)('a'*2048)
            with self.assertRaises(DeliveryError): WeComSender(self.path)('a'*2049)
