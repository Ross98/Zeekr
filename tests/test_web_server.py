"""Offline tests: identifiers and observations are synthetic, never owner records."""
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest

from zeekr_control.client import ApiError


class FakeClient:
    fail = False

    def __init__(self, session):
        pass

    def vehicles(self):
        return [{'vin': 'L6T79X2Z0NP000001'}, {'vin': 'L6T79X2Z0NP000002'}]

    def status(self, vin):
        if self.fail:
            raise ApiError('测试：会话失效')
        return {'updateTime': 1704067200000, 'accessToken': 'NEVER-EXPOSE',
                'position': {'latitude': 111600000, 'longitude': 435600000,
                             'posCanBeTrusted': True, 'marsCoordinates': False},
                'additionalVehicleStatus': {'electricVehicleStatus': {'chargeLevel': 62}}}


class WebServerTests(unittest.TestCase):
    def test_deep_archive_payload_returns_validation_error_and_preserves_cached_vehicle(self):
        from zeekr_control.snapshot_archive import SnapshotArchive
        self.post('/api/refresh',{'vehicle':1})
        expected=self.request('GET','/api/state')[1]['model']
        reader=self.app.archive_reader
        writer=SnapshotArchive(reader.root)
        writer.append(self.app.session_key,self.app.vehicle_key,
                      json.dumps(FakeClient({}).status('synthetic')),
                      1704067200000,1704067200000,1704067200000,'monitor')
        writer.append(self.app.session_key,self.app.vehicle_key,
                      '{"extra":'+'['*10000+'0'+']'*10000+'}',
                      1704067201000,1704067201000,1704067201000,'monitor')
        items=reader.timeline(self.app.session_key,self.app.vehicle_key,'2024-01-01')['items']
        valid,bad=items[0]['key'],items[-1]['key']
        shard=reader.root/'2024'/'01.sqlite3';before=shard.read_bytes()
        for route in ('/api/insights/snapshot?id='+bad,
                      '/api/insights/compare?before='+valid+'&after='+bad):
            code,result=self.request('GET',route)
            self.assertEqual(code,400,result)
        self.assertEqual(self.request('GET','/api/insights/snapshot?id='+valid)[0],200)
        self.assertEqual(self.request('GET','/api/state')[1]['model'],expected)
        self.assertEqual(shard.read_bytes(),before)

    def test_notification_diagnostics_require_vehicle_connection(self):
        code,result=self.request('GET','/api/notifications/health')
        self.assertEqual(code,400,result)
        self.assertIn('车辆缓存',result['error'])
        self.app.session_path.unlink()
        code,result=self.request('GET','/api/notifications/health')
        self.assertEqual(code,400,result)
        self.assertIn('请先连接车辆账号',result['error'])
        self.assertFalse((self.app.session_path.parent/'system-notifications.sqlite3').exists())

    def test_database_size_failure_keeps_cached_state_and_reports_unknown(self):
        from unittest.mock import patch
        self.post('/api/refresh',{'vehicle':1})
        expected=self.request('GET','/api/state')[1]['model']
        original=Path.stat
        def fail_database_stat(path,*args,**kwargs):
            if path==self.app.database_path:raise PermissionError('PRIVATE synthetic metadata failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'stat',fail_database_stat):
            code,result=self.request('GET','/api/state')
        self.assertEqual(code,200,result)
        self.assertEqual(result['model'],expected)
        self.assertIsNone(result['storage_bytes'])
        self.assertEqual(result['range_attainment']['status'],'unavailable')
        self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertIn('轨迹存储',result['error'])

    def test_directory_is_not_reported_as_database_file_size(self):
        self.post('/api/refresh',{'vehicle':1})
        expected=self.request('GET','/api/state')[1]['model']
        self.app.database_path.unlink(missing_ok=True);self.app.database_path.mkdir()
        code,result=self.request('GET','/api/state')
        self.assertEqual(code,200,result)
        self.assertEqual(result['model'],expected)
        self.assertIsNone(result['storage_bytes'])

    def test_invalid_optional_profile_text_does_not_break_json_state(self):
        import hashlib
        from unittest.mock import patch
        from zeekr_control.profiles import vehicle_profile
        config=self.root/'profiles.json'
        key=hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest()
        config.write_text(json.dumps({'vehicles':{key:{'name':'\ud800','range_km':546,'range_standard':'CLTC'}}}))
        with patch('zeekr_control.web.vehicle_profile',
                   side_effect=lambda key,number,count:vehicle_profile(key,number,count,config)):
            code,result=self.post('/api/refresh',{'vehicle':1})
            self.assertEqual(code,200,result)
            code,result=self.request('GET','/api/state')
            self.assertEqual(code,200,result)
        self.assertEqual(result['model']['metrics']['battery'],'62%')
        self.assertEqual(result['profile']['name'],'车辆 1')
        self.assertEqual(result['profile']['range_km'],546)

    def test_bad_vehicle_time_is_archived_as_unknown_without_losing_car_state(self):
        from unittest.mock import patch
        raw=FakeClient(None).status('synthetic');raw['updateTime']='²'
        with patch.object(FakeClient,'status',return_value=raw):
            code,result=self.post('/api/refresh',{'vehicle':1})
        self.assertEqual(code,200,result)
        self.assertEqual(result['refresh_result'],'time_unknown')
        self.assertEqual(result['model']['metrics']['battery'],'62%')
        snapshot=self.app.snapshot_store.read(self.app.session_key,self.app.vehicle_key)
        self.assertIsNone(snapshot['state_time'])
        self.assertEqual(snapshot['raw']['updateTime'],'²')
        self.assertEqual(self.request('GET','/api/state')[0],200)
        code,result=self.post('/api/refresh',{'vehicle':1})
        self.assertEqual(code,200,result)
        self.assertEqual(result['refresh_result'],'new')

    def test_one_extreme_vehicle_field_does_not_break_cached_model(self):
        from unittest.mock import patch
        raw=FakeClient(None).status('synthetic')
        raw['additionalVehicleStatus']['electricVehicleStatus']['distanceToEmptyOnBatteryOnly']='1e999999999'
        with patch.object(FakeClient,'status',return_value=raw):
            code,result=self.post('/api/refresh',{'vehicle':1})
        self.assertEqual(code,200,result)
        self.assertEqual(result['model']['metrics']['battery'],'62%')
        self.assertEqual(result['model']['metrics']['range'],'未知')
        code,result=self.request('GET','/api/state')
        self.assertEqual(code,200,result)
        self.assertEqual(result['model']['metrics']['battery'],'62%')
        self.assertEqual(result['model']['metrics']['range'],'未知')
        snapshot=self.app.snapshot_store.read(self.app.session_key,self.app.vehicle_key)
        self.assertEqual(snapshot['raw']['additionalVehicleStatus']['electricVehicleStatus']['distanceToEmptyOnBatteryOnly'],
                         '1e999999999','display validation must retain original evidence')

    def test_invalid_monitor_timestamps_preserve_state_and_show_unknown(self):
        from zeekr_control.storage import save
        self.post('/api/refresh',{'vehicle':1})
        expected=self.request('GET','/api/state')[1]['model']
        path=self.app.session_path.parent/'monitor-health.json'
        save(path,{'status':'fresh','heartbeat':'1e999999999',
                   'last_success':'1e999999999','last_new':'1e999999999'})
        before=path.read_bytes()
        code,result=self.request('GET','/api/state')
        self.assertEqual(code,200,result)
        self.assertEqual(result['model'],expected)
        self.assertEqual(result['recording']['last_sample'],'未知')
        self.assertEqual(result['recording']['last_new'],'未知')
        self.assertFalse(result['monitoring']['online'])
        self.assertEqual(path.read_bytes(),before)

    def test_invalid_release_metadata_does_not_hide_state_or_break_settings_save(self):
        from unittest.mock import patch
        from zeekr_control.release_info import read_release
        root=self.root/'release';root.mkdir()
        (root/'release-manifest.json').write_text('['*10000+'0'+']'*10000)
        self.post('/api/refresh',{'vehicle':1})
        expected=self.request('GET','/api/state')[1]['model']
        with patch('zeekr_control.web.read_release',side_effect=lambda:read_release(root)):
            code,state=self.request('GET','/api/state')
            self.assertEqual(code,200,state)
            self.assertEqual(state['release']['status'],'invalid')
            self.assertEqual(state['model'],expected)
            code,state=self.post('/api/recording',{'active':False,'interval':20})
            self.assertEqual(code,200,state)
            self.assertFalse(state['recording']['active'])
            self.assertEqual(state['recording']['interval'],20)

    def test_incomplete_or_ambiguous_request_body_cannot_change_recording(self):
        import socket
        from zeekr_control.storage import load
        payload=b'{"active":false,"interval":20}'
        path=self.app.session_path.parent/'sampling.json'
        variants=(
            ('truncated',[f'Content-Length: {len(payload)+10}']),
            ('duplicate',[f'Content-Length: {len(payload)}',f'Content-Length: {len(payload)+10}']),
            ('transfer-encoding',[f'Content-Length: {len(payload)}','Transfer-Encoding: chunked']),
            ('signed-length',[f'Content-Length: +{len(payload)}']),
        )
        for name,framing in variants:
            with self.subTest(framing=name):
                self.assertEqual(self.post('/api/recording',{'active':True,'interval':30})[0],200)
                before=path.read_bytes()
                headers=['POST /api/recording HTTP/1.1',f'Host: 127.0.0.1:{self.server.server_port}',
                         f'Origin: {self.origin}',f'X-Request-Key: {self.key}',
                         'Content-Type: application/json',*framing,'Connection: close','','']
                with socket.create_connection(('127.0.0.1',self.server.server_port),timeout=5) as connection:
                    connection.sendall('\r\n'.join(headers).encode()+payload)
                    connection.shutdown(socket.SHUT_WR)
                    response=http.client.HTTPResponse(connection)
                    response.begin();body=response.read()
                self.assertEqual(response.status,400,body)
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(load(path)['enabled'],'true')
                self.assertIsNone(self.app.error)
        self.assertEqual(self.post('/api/recording',{'active':False,'interval':20})[0],200)
        self.assertEqual(load(path)['enabled'],'false')

    def test_interval_only_save_preserves_authoritative_switch_and_rejects_mixed_operations(self):
        from zeekr_control.storage import load
        path=self.app.session_path.parent/'sampling.json'
        for active in (False,True):
            self.post('/api/recording',{'active':active,'interval':30})
            code,result=self.post('/api/recording',{'operation':'interval','interval':60})
            self.assertEqual(code,200,result)
            self.assertEqual(result['recording']['active'],active)
            self.assertEqual(load(path),{'enabled':'true' if active else 'false','interval':'60'})
        before=path.read_bytes()
        for payload in ({'operation':'interval','active':False,'interval':20},
                        {'operation':'interval','interval':None},{'operation':'interval','interval':True},
                        {'operation':'other','active':False,'interval':20}):
            with self.subTest(payload=payload):
                self.assertEqual(self.post('/api/recording',payload)[0],400)
                self.assertEqual(path.read_bytes(),before)

    def test_sampling_save_contention_returns_503_without_modifying_controls(self):
        from zeekr_control.delivery_state import delivery_lock
        from unittest.mock import patch
        root=self.app.session_path.parent
        self.post('/api/recording',{'active':False,'interval':30})
        before=(root/'sampling.json').read_bytes()
        with delivery_lock(root/'sampling-settings.lock'),patch('zeekr_control.sampling.time.sleep',return_value=None):
            code,result=self.post('/api/recording',{'operation':'interval','interval':60})
        self.assertEqual(code,503,result)
        self.assertIn('设置正在保存',result['error'])
        self.assertEqual((root/'sampling.json').read_bytes(),before)
        self.assertEqual(self.post('/api/recording',{'operation':'interval','interval':60})[0],200)

    def test_explicit_full_recording_settings_repair_corrupt_controls_without_cloud_reads(self):
        from unittest.mock import patch
        from zeekr_control.storage import save,load
        self.post('/api/refresh',{'vehicle':1})
        expected=self.request('GET','/api/state')[1]['model']
        path=self.app.session_path.parent/'sampling.json'
        for fault in ('json','enabled','interval','permissions'):
            with self.subTest(fault=fault):
                save(path,{'enabled':'true','interval':'30'})
                if fault=='json':path.write_text('{broken')
                elif fault=='enabled':save(path,{'enabled':'broken','interval':'30'})
                elif fault=='interval':save(path,{'enabled':'false','interval':'broken'})
                else:path.chmod(0o644)
                with patch.object(FakeClient,'vehicles',side_effect=AssertionError('unexpected cloud read')),\
                     patch.object(FakeClient,'status',side_effect=AssertionError('unexpected cloud read')):
                    self.assertIsNone(self.request('GET','/api/state')[1]['recording']['active'])
                    code,result=self.post('/api/recording',{'active':True,'interval':20})
                self.assertEqual(code,200,result)
                self.assertEqual(result['model'],expected)
                self.assertTrue(result['recording']['active'])
                self.assertEqual(result['recording']['interval'],20)
                self.assertEqual(load(path),{'enabled':'true','interval':'20'})
                self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_bad_monitor_event_metadata_cannot_break_browser_json_state(self):
        from zeekr_control.monitor import Monitor
        from zeekr_control.storage import save
        self.post('/api/refresh',{'vehicle':1})
        monitor=Monitor(self.app.database_path)
        with monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                       ('event',self.app.vehicle_key,'trip_end','{}','PRIVATE',1))
        save(self.app.session_path.parent/'monitor-health.json',dict(status='fresh',heartbeat='1000000'))
        expected=self.request('GET','/api/state')[1]['model']
        for field,value in (('created',float('inf')),('kind',b'PRIVATE'),('delivery',b'PRIVATE')):
            with self.subTest(field=field):
                with monitor.tracks.connect() as db:
                    db.execute("UPDATE monitor_events SET kind='trip_end',created=1,delivery='sent' WHERE id='event'")
                    db.execute('UPDATE monitor_events SET '+field+"=? WHERE id='event'",(value,))
                original=self.app.database_path.read_bytes()
                code,result=self.request('GET','/api/state')
                self.assertEqual(code,200,result)
                self.assertEqual(result['model'],expected)
                self.assertEqual(len(result['monitoring']['events']),1)
                self.assertNotIn('PRIVATE',json.dumps(result,allow_nan=False))
                self.assertEqual(self.app.database_path.read_bytes(),original)

    def test_unsafe_event_storage_returns_controlled_error_without_hiding_vehicle_cache(self):
        from zeekr_control.monitor import Monitor
        self.post('/api/refresh',{'vehicle':1})
        monitor=Monitor(self.app.database_path)
        with monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                       ('event',self.app.vehicle_key,'trip_end',json.dumps(dict(end_time=1704126600000,distance_km=12)),'PRIVATE',1))
        expected=self.request('GET','/api/state')[1]['model']
        path=self.app.database_path;path.chmod(0o644);before=path.read_bytes()
        code,result=self.request('GET','/api/state')
        self.assertEqual(code,200,result)
        self.assertEqual(result['model'],expected)
        self.assertIsNone(result['recent_events']['trip_end'])
        self.assertIn('本地事件',result['recent_events']['error'])
        code,result=self.request('GET','/api/events?date=2024-01-02&kind=trip_end')
        self.assertEqual(code,500,result)
        self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(path.stat().st_mode & 0o777,0o644)

    def test_invalid_collector_times_never_report_false_online_or_hide_cached_state(self):
        from zeekr_control.storage import save
        self.post('/api/refresh',{'vehicle':1})
        expected=self.request('GET','/api/state')[1]['model']
        path=self.app.session_path.parent/'monitor-health.json'
        for stamp,deadline in (('0','inf'),('-inf','inf'),('1000000','1e309'),('broken','broken')):
            with self.subTest(stamp=stamp,deadline=deadline):
                save(path,dict(status='fresh',heartbeat=stamp,next_check=deadline))
                original=path.read_bytes()
                code,result=self.request('GET','/api/state')
                self.assertEqual(code,200,result)
                self.assertEqual(result['model'],expected)
                self.assertEqual(result['monitoring']['status'],'fresh')
                self.assertFalse(result['monitoring']['online'])
                self.assertEqual(result['recording']['status'],'offline')
                code,health=self.request('GET','/api/notifications/health')
                self.assertEqual(code,200,health)
                self.assertFalse(health['services']['collector']['online'])
                self.assertEqual(path.read_bytes(),original)

    def test_deep_report_payload_does_not_break_notification_health_endpoint(self):
        from zeekr_control.periodic_report import PeriodicDelivery
        from zeekr_control.personal_store import account_scope
        self.post('/api/refresh',{'vehicle':1})
        owner=account_scope(self.app._read_session());vehicle=self.app.vehicle_key
        delivery=PeriodicDelivery(self.app.session_path.parent/'periodic-reports.sqlite3')
        with delivery.connect() as db,db:
            db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?,?)',('bad','['*10000+'0'+']'*10000,'light','pending','pending',0,0,0))
            db.execute('INSERT INTO report_delivery_metadata(id,owner_key,vehicle_key) VALUES(?,?,?)',('bad',owner,vehicle))
        before=delivery.path.read_bytes()
        code,result=self.request('GET','/api/notifications/health')
        self.assertEqual(code,200,result)
        self.assertFalse(result['summary']['complete'])
        self.assertIn('reports',result['unavailable_sources'])
        self.assertEqual(delivery.path.read_bytes(),before)

    def test_bad_sampling_controls_keep_cached_state_available(self):
        from zeekr_control.storage import save
        self.post('/api/refresh',{'vehicle':1})
        expected=self.request('GET','/api/state')[1]['model']
        path=self.app.session_path.parent/'sampling.json'
        for fault in ('json','interval','enabled','permissions'):
            with self.subTest(fault=fault):
                save(path,{'enabled':'true','interval':'30'})
                if fault=='json':path.write_text('{broken')
                elif fault=='interval':save(path,{'interval':'broken'})
                elif fault=='enabled':save(path,{'enabled':'broken'})
                else:path.chmod(0o644)
                original=path.read_bytes();mode=path.stat().st_mode
                code,result=self.request('GET','/api/state')
                self.assertEqual(code,200,result)
                self.assertEqual(result['model'],expected)
                self.assertIsNone(result['recording']['active'])
                self.assertIsNone(result['recording']['interval'])
                self.assertEqual(result['recording']['status'],'failed')
                self.assertIn('采集配置',result['recording']['error'])
                self.assertEqual(path.read_bytes(),original)
                self.assertEqual(path.stat().st_mode,mode)
        save(path,{'enabled':'false','interval':'10'})
        code,result=self.request('GET','/api/state')
        self.assertEqual(code,200,result)
        self.assertEqual(result['recording']['status'],'paused')
        self.assertEqual(result['recording']['interval'],10)

    def test_invalid_monitor_interval_does_not_break_cached_state(self):
        from zeekr_control.storage import save
        self.post('/api/refresh',{'vehicle':1})
        expected=self.request('GET','/api/state')[1]['model']
        save(self.app.session_path.parent/'monitor-health.json',{'status':'retrying','interval':'broken'})
        code,result=self.request('GET','/api/state')
        self.assertEqual(code,200,result)
        self.assertEqual(result['model'],expected)
        self.assertEqual(result['recording']['interval'],30)
        self.assertIsNone(result['recording']['effective_interval'])

    def test_bad_snapshot_metadata_is_contained_even_without_revision_change(self):
        import sqlite3
        self.post('/api/refresh',{'vehicle':1})
        expected=self.request('GET','/api/state')[1]['model']
        with sqlite3.connect(self.app.snapshot_store.path) as db:
            db.execute("UPDATE snapshots SET fetched_at='broken'")
        code,result=self.request('GET','/api/state')
        self.assertEqual(code,200,result)
        self.assertEqual(result['model'],expected)
        self.assertIn('缓存',result['error'])
        self.assertIsNone(self.app.snapshot_revision)
        self.assertIsInstance(self.app.read_at,int)

    def test_bad_latest_cache_keeps_state_available_and_valid_refresh_repairs_it(self):
        import sqlite3
        self.post('/api/refresh',{'vehicle':1})
        expected = self.request('GET','/api/state')[1]['model']
        with sqlite3.connect(self.app.snapshot_store.path) as db:
            db.execute('UPDATE snapshots SET raw=?,revision=revision+1',('['*1200+'0'+']'*1200,))
        code, result = self.request('GET','/api/state')
        self.assertEqual(code,200,result)
        self.assertEqual(result['model'],expected)
        self.assertIn('缓存',result['error'])
        self.app.raw = self.app.model = None
        code, empty = self.request('GET','/api/state')
        self.assertEqual(code,200,empty)
        self.assertIsNone(empty['model'])
        self.assertIn('缓存',empty['error'])
        code, refreshed = self.post('/api/refresh',{'vehicle':1})
        self.assertEqual(code,200,refreshed)
        self.assertIsNone(refreshed['error'])
        self.assertEqual(refreshed['model'],expected)

    def test_late_older_fetch_keeps_accepted_state_and_reports_superseded(self):
        import time
        from unittest.mock import patch
        from zeekr_control.snapshots import session_scope
        self.post('/api/refresh',{'vehicle':1})
        scope = session_scope(self.app._read_session())
        vehicle = self.app.vehicle_key
        saved = self.app.snapshot_store.read(scope,vehicle)
        raw = saved['raw']
        raw['additionalVehicleStatus']['electricVehicleStatus']['chargeLevel'] = 90
        stamp = int(time.time()*1000)
        self.app.snapshot_store.publish(scope,vehicle,raw,stamp,fetched_at=stamp)
        with patch.object(FakeClient,'last_query_fetched_at',(stamp-1000)/1000,create=True):
            code, result = self.post('/api/refresh',{'vehicle':1})
        self.assertEqual(code,200,result)
        self.assertEqual(result['refresh_result'],'superseded')
        self.assertEqual(self.app.snapshot_store.read(scope,vehicle)['raw']
                         ['additionalVehicleStatus']['electricVehicleStatus']['chargeLevel'],90)

    def test_report_http_keeps_completed_history_when_active_state_is_invalid(self):
        from zeekr_control.monitor import Monitor
        self.post('/api/refresh', {'vehicle': 1})
        monitor = Monitor(self.app.database_path)
        summary = json.dumps(dict(start_time=1704126500000, end_time=1704126600000,
                                  duration_seconds=100, distance_km=2.5, partial=False))
        with monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                       ('valid-report',self.app.vehicle_key,'trip_end',summary,'PRIVATE',1))
            db.execute('INSERT OR REPLACE INTO monitor_state(vehicle,payload) VALUES(?,?)',
                       (self.app.vehicle_key,'['*1200+'0'+']'*1200))
        code, result = self.request('GET', '/api/insights/report?period=month&date=2024-01-02')
        self.assertEqual(code, 200, result)
        self.assertIsNone(result['open_trip'])
        self.assertEqual(result['current']['totals']['distance_km'], 2.5)

    def test_charging_series_http_preserves_hole_at_invalid_observation(self):
        from zeekr_control.monitor import Monitor
        from test_charging_analytics import BASE,sample
        self.post('/api/refresh',{'vehicle':1})
        monitor=Monitor(self.app.database_path)
        with monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                ('hole',self.app.vehicle_key,'charge_end',json.dumps({'start_time':BASE,
                 'end_time':BASE+120000,'duration_seconds':120,'partial':True}),'PRIVATE',BASE+120000))
            for i in range(3):
                point=sample(BASE+i*60000,20+i,7)
                if i==1:point['state_time']=None
                db.execute('INSERT INTO report_observations VALUES(?,?,?,?,?)',
                    (self.app.vehicle_key,BASE+i*60000,BASE+i*60000,json.dumps(point),'synthetic'))
        for view in ('power-soc','electrical'):
            code,series=self.request('GET','/api/charging/series?id=hole&view='+view)
            self.assertEqual(code,200,series)
            self.assertEqual(series['raw_count'],2)
            self.assertTrue(series['has_gaps'])
            self.assertEqual(len(series['segments']),2)

    def test_bad_history_row_does_not_break_event_http_or_hide_latest_valid_event(self):
        from zeekr_control.monitor import Monitor
        self.post('/api/refresh',{'vehicle':1})
        monitor=Monitor(self.app.database_path)
        valid=json.dumps({'start_time':1704126500000,'end_time':1704126600000,
                          'duration_seconds':100,'distance_km':2.5,'partial':False})
        deep='{"end_time":1704126660000,"extra":'+('['*10000)+'0'+(']'*10000)+'}'
        charge=json.dumps({'start_time':1704126500000,'end_time':1704126600000,
            'report_v2':{'schema_version':2,'start':{},'end':{},
                         'metrics':{'sampled_peak_kw':10**400,'average_power_kw':6.5}}})
        with monitor.tracks.connect() as db:
            db.executemany('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',[
                ('valid',self.app.vehicle_key,'trip_end',valid,'PRIVATE',1),
                ('deep',self.app.vehicle_key,'trip_end',deep,'PRIVATE',2),
                ('charge',self.app.vehicle_key,'charge_end',charge,'PRIVATE',3)])
        code,page=self.request('GET','/api/events?date=2024-01-02&kind=trip_end')
        self.assertEqual(code,200)
        self.assertEqual([row['id'] for row in page['events']],['valid'])
        code,page=self.request('GET','/api/events?date=2024-01-02&kind=charge_end')
        self.assertEqual(code,200)
        self.assertIsNone(page['events'][0]['charging_details']['metrics']['sampled_peak_kw'])
        code,state=self.request('GET','/api/state')
        self.assertEqual(code,200)
        self.assertEqual(state['recent_events']['trip_end']['id'],'valid')
        self.assertEqual(state['range_attainment']['status'],'unavailable')

    def test_calendar_overflow_returns_400_without_breaking_state(self):
        self.post('/api/refresh',{'vehicle':1})
        for route in ('/api/tracks?date=9999-12-31',
                      '/api/events?date=9999-12-31&kind=trip_end',
                      '/api/insights/report?period=month&date=9999-12-01',
                      '/api/insights/report?period=week&date=9999-12-28'):
            with self.subTest(route=route):
                code,body=self.request('GET',route)
                self.assertEqual(code,400)
                self.assertIn('error',body)
        self.assertEqual(self.request('GET','/api/state')[0],200)

    def test_vehicle_parameters_are_cached_complete_and_keep_failed_snapshot(self):
        from unittest.mock import patch
        with patch.object(FakeClient, 'status', side_effect=AssertionError('must not query vehicle')):
            code, empty = self.request('GET', '/api/vehicle/parameters')
        self.assertEqual(code, 200)
        self.assertEqual(empty['counts']['missing'], 217)
        initial = self.post('/api/refresh', {'vehicle': 1})[1]
        with patch.object(FakeClient, 'status', side_effect=AssertionError('must not query vehicle')):
            code, data = self.request('GET', '/api/vehicle/parameters')
        self.assertEqual(code, 200)
        self.assertEqual(data['snapshot_revision'], initial['snapshot_revision'])
        self.assertEqual(data['vehicle'], 1)
        self.assertNotIn('NEVER-EXPOSE', json.dumps(data))
        FakeClient.fail = True
        self.assertEqual(self.post('/api/refresh', {'vehicle': 1})[0], 502)
        failed = self.request('GET', '/api/vehicle/parameters')[1]
        self.assertEqual(data['fields'], failed['fields'])
        self.assertEqual(data['read_time'], failed['read_time'])

    def test_vehicle_parameters_follow_current_vehicle_and_assets_load(self):
        self.post('/api/refresh', {'vehicle': 1})
        self.post('/api/refresh', {'vehicle': 2})
        code, data = self.request('GET', '/api/vehicle/parameters')
        self.assertEqual(code, 200)
        self.assertEqual(data['vehicle'], 2)
        for asset in ('/vehicle.js', '/vehicle.css'):
            self.assertEqual(self.request('GET', asset)[0], 200)

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('zeekr_control.web'), 'Web 服务尚未实现')
        from zeekr_control.web import App, make_server
        from zeekr_control.storage import save
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        save(self.root / 'private' / 'session.json', {'accessToken': 'NEVER-EXPOSE', 'userId': 'private'})
        self.app = App(self.root / 'private' / 'session.json', self.root / 'private' / 'tracks.sqlite3', FakeClient)
        self.server = make_server(self.app, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:%d' % self.server.server_port
        self.key = self.request('GET', '/api/state')[1]['request_key']
        self.addCleanup(self.cleanup)

    def cleanup(self):
        FakeClient.fail = False
        self.app.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        data = json.dumps(body) if body is not None else None
        connection.request(method, path, data, headers or {})
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        connection.close()
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw.decode()

    def post(self, path, body):
        return self.request('POST', path, body, {'Origin': self.origin, 'Content-Type': 'application/json',
                                               'X-Request-Key': self.key})

    def test_refresh_redacts_identity_and_does_not_start_recording(self):
        code, data = self.post('/api/refresh', {'vehicle': 1})
        self.assertEqual(code, 200)
        self.assertEqual(data['model']['metrics']['battery'], '62%')
        self.assertTrue(data['recording']['active'])
        self.assertEqual(data['recording']['status'], 'offline')
        self.assertNotIn('NEVER-EXPOSE', str(data))
        self.assertNotIn('L6T79', str(data))
        self.assertNotIn('111600000', str(data))
        self.assertEqual(self.request('GET', '/api/location')[1]['latitude'], 31)

    def test_monitor_status_is_visible_without_exposing_webhook(self):
        from zeekr_control.storage import save
        save(self.root / 'private' / 'monitor-health.json',
             {'status': 'fresh', 'heartbeat': '1704067200000', 'trip': 'driving'})
        save(self.root / 'private' / 'wecom-webhook.json', {'webhook_url': 'SECRET-WEBHOOK'})
        code, data = self.request('GET', '/api/state')
        self.assertEqual(code, 200)
        self.assertEqual(data['monitoring']['status'], 'fresh')
        self.assertFalse(data['monitoring']['online'])
        self.assertNotIn('SECRET-WEBHOOK', json.dumps(data))

    def test_cross_origin_mutation_and_rebinding_are_rejected(self):
        self.assertEqual(self.request('POST', '/api/refresh', {}, {'Origin': 'https://evil.invalid',
            'Content-Type': 'application/json', 'X-Request-Key': self.key})[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Host': 'evil.invalid'})[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.request('POST', '/api/refresh', {})[0], 403)

    def test_failure_keeps_original_model_and_timestamp(self):
        original = self.post('/api/refresh', {'vehicle': 1})[1]
        FakeClient.fail = True
        self.assertEqual(self.post('/api/refresh', {'vehicle': 1})[0], 502)
        later = self.request('GET', '/api/state')[1]
        self.assertEqual(later['model'], original['model'])
        self.assertEqual(later['read_at'], original['read_at'])
        self.assertTrue(later['error'])

    def test_recording_controls_shared_backend_and_validates_interval(self):
        from zeekr_control.storage import load
        self.assertEqual(self.app.state()['recording']['interval'], 30)
        for invalid in (0, 9, 61, True, 30.5, '30'):
            self.assertEqual(self.post('/api/recording', {'active': True, 'interval': invalid})[0], 400)
        self.assertEqual(self.post('/api/recording', {'active': 'false', 'interval': 60})[0], 400)
        self.assertEqual(self.post('/api/recording', {'active': True, 'interval': 60})[0], 200)
        self.assertEqual(load(self.app.session_path.parent / 'sampling.json')['enabled'], 'true')
        self.assertEqual(self.post('/api/recording', {'active': False, 'interval': 60})[0], 200)
        self.assertEqual(load(self.app.session_path.parent / 'sampling.json')['enabled'], 'false')
        for interval in (10, 15, 30, 60):
            code, result = self.post('/api/recording', {'active': False, 'interval': interval})
            self.assertEqual(code, 200)
            self.assertEqual(result['recording']['interval'], interval)
            self.assertFalse(result['recording']['active'])
        self.post('/api/recording', {'active': True, 'interval': 10})
        self.assertEqual(self.post('/api/recording', {'active': False})[1]['recording']['interval'], 10)
        self.assertEqual(load(self.app.session_path.parent / 'sampling.json')['interval'], '10')


    def test_retired_parking_page_asset_is_not_served(self):
        self.assertEqual(self.request('GET','/parking.js')[0],404)

    def test_retired_cloud_history_has_no_routes_or_state(self):
        self.post('/api/refresh', {'vehicle': 1})
        before=self.app.session_path.read_bytes()
        for route in ('/api/history?date=2024-01-01','/api/history/points?trip=old','/history.js'):
            self.assertEqual(self.request('GET',route)[0],404,route)
        self.assertNotIn('history',self.request('GET','/api/state')[1])
        self.assertEqual(self.app.session_path.read_bytes(),before)
        self.assertEqual(self.request('GET', '/api/tracks?date=wrong')[0], 400)

    def test_static_traversal_and_unknown_api_not_served(self):
        self.assertEqual(self.request('GET', '/../../Myconfig.md')[0], 404)
        self.assertEqual(self.request('GET', '/api/unknown')[0], 404)

    def test_charging_process_returns_summary_and_series_together(self):
        self.post('/api/refresh', {'vehicle': 1})
        code, data = self.request('GET', '/api/charging/process?id=current&view=power-soc')
        self.assertEqual(code, 200)
        self.assertEqual(data['session']['status'], 'empty')
        self.assertEqual(data['series']['points'], [])

    def test_local_tracks_remain_readable_without_cloud_refresh_after_restart(self):
        from zeekr_control.web import App
        from zeekr_control.tracks import TrackStore
        TrackStore(self.app.database_path).record('synthetic', FakeClient({}).status('synthetic'), 1704067200000, 180)
        reopened = App(self.app.session_path, self.app.database_path, FakeClient)
        try:
            self.assertIsNone(reopened.model)
            self.assertEqual(len(reopened.state()['archived_vehicles']), 1)
            self.assertEqual(reopened.tracks('2024-01-01')['count'], 1)
        finally:
            reopened.close()

    def test_saved_background_snapshot_restores_without_gateway_query(self):
        from zeekr_control.snapshots import SnapshotStore, session_scope
        from zeekr_control.storage import load, save
        from zeekr_control.web import App
        vehicle_key = __import__('hashlib').sha256(b'L6T79X2Z0NP000001').hexdigest()
        save(self.app.session_path.parent / 'monitor-binding.json', {'vehicle_key': vehicle_key})
        SnapshotStore(self.app.session_path.parent / 'snapshots.sqlite3').publish(
            session_scope(load(self.app.session_path)), vehicle_key,
            FakeClient({}).status('synthetic'), 1704067201000)
        class NoGateway(FakeClient):
            def vehicles(self): raise AssertionError('GET /api/state must stay local')
            def status(self, vin): raise AssertionError('GET /api/state must stay local')
        reopened = App(self.app.session_path, self.app.database_path, NoGateway)
        try:
            result = reopened.state()
            self.assertEqual(result['model']['metrics']['battery'], '62%')
            self.assertEqual(result['snapshot_revision'], 1)
        finally:
            reopened.close()

    def test_events_endpoint_filters_current_vehicle_and_redacts_location(self):
        import json
        self.post('/api/refresh', {'vehicle': 1})
        from zeekr_control.monitor import Monitor
        monitor = Monitor(self.app.database_path)
        summary = {'start_time': 1704126500000, 'end_time': 1704126600000,
                   'duration_seconds': 100, 'distance_km': 2.5, 'partial': False,
                   'start_location': {'latitude': 31}, 'start_address': 'PRIVATE'}
        with monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                       ('event-a', self.app.vehicle_key, 'trip_end', json.dumps(summary), 'PRIVATE MESSAGE', 1))
            db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                       ('event-b', 'other', 'trip_end', json.dumps(summary), 'PRIVATE MESSAGE', 2))
        code, result = self.request('GET', '/api/events?date=2024-01-02&kind=trip_end')
        self.assertEqual(code, 200)
        self.assertEqual([event['id'] for event in result['events']], ['event-a'])
        self.assertNotIn('PRIVATE', str(result))

    def test_charging_analytics_routes_validate_and_stay_local(self):
        self.post('/api/refresh', {'vehicle': 1})
        self.assertEqual(self.request('GET', '/api/charging/session?id=current')[0], 200)
        self.assertEqual(self.request('GET', '/api/charging/series?id=current&view=wrong')[0], 400)
        code, result = self.request('GET', '/api/charging/statistics?days=30&mode=all')
        self.assertEqual(code, 200)
        self.assertEqual(result['summary']['ended_count'], 0)


    def test_background_failure_visible_in_shared_recording_state(self):
        import time
        from zeekr_control.storage import save
        self.post('/api/refresh', {'vehicle': 1})
        save(self.app.session_path.parent / 'monitor-health.json',
             {'status':'blocked', 'heartbeat':str(int(time.time()*1000)), 'error':'测试：会话失效'})
        result = self.app.state()
        self.assertEqual(result['recording']['status'], 'failed')
        self.assertEqual(result['recording']['error'], '采集后台异常，请检查服务状态。')
        self.assertEqual(result['model']['metrics']['battery'], '62%')


    def test_refresh_distinguishes_cache_unchanged_and_new_data(self):
        first = self.post('/api/refresh', {'vehicle': 1})[1]
        self.assertEqual(first.get('refresh_result'), 'new')
        second = self.post('/api/refresh', {'vehicle': 1})[1]
        self.assertEqual(second['refresh_result'], 'unchanged')
        from unittest.mock import patch
        with patch.object(FakeClient, 'last_query_cached', True, create=True):
            cached = self.post('/api/refresh', {'vehicle': 1})[1]
        self.assertEqual(cached['refresh_result'], 'cached')
        self.assertEqual(self.post('/api/refresh', {'vehicle': 2})[1]['refresh_result'], 'new')

    def test_refresh_identifies_same_time_revision_and_new_time_same_values(self):
        from unittest.mock import patch
        self.post('/api/refresh', {'vehicle': 1})
        raw = FakeClient({}).status('synthetic')
        raw['additionalVehicleStatus']['electricVehicleStatus']['chargeLevel'] = 61
        with patch.object(FakeClient, 'status', return_value=raw):
            revised = self.post('/api/refresh', {'vehicle': 1})[1]
        self.assertEqual(revised['refresh_result'], 'revision')
        self.assertEqual(revised['model']['metrics']['battery'], '61%')
        raw['updateTime'] += 60000
        with patch.object(FakeClient, 'status', return_value=raw):
            self.assertEqual(self.post('/api/refresh', {'vehicle': 1})[1]['refresh_result'], 'new')

    def test_recording_lifecycle_distinguishes_offline_paused_active(self):
        import time
        from zeekr_control.storage import save
        self.assertEqual(self.app.state()['recording']['status'], 'offline')
        save(self.app.session_path.parent / 'monitor-health.json',
             {'status':'fresh', 'heartbeat':str(int(time.time()*1000)), 'interval':'300'})
        self.assertEqual(self.app.state()['recording']['status'], 'active')
        self.assertEqual(self.app.state()['recording']['effective_interval'], 300)
        self.post('/api/recording', {'active': False, 'interval': 60})
        self.assertEqual(self.app.state()['recording']['status'], 'paused')


    def test_profiles_do_not_apply_same_car_to_multiple_vehicles(self):
        data = self.post('/api/refresh', {'vehicle': 2})[1]
        self.assertEqual(data.get('profile', {}).get('name'), '车辆 2')
        self.assertFalse(data['profile']['image'])

    def test_manual_refresh_failure_does_not_stop_shared_backend(self):
        from zeekr_control.storage import load
        self.post('/api/recording', {'active': True, 'interval': 60})
        FakeClient.fail = True
        self.assertEqual(self.post('/api/refresh', {'vehicle': 1})[0], 502)
        self.assertEqual(load(self.app.session_path.parent / 'sampling.json')['enabled'], 'true')


    def test_missing_and_older_vehicle_time_never_claim_new_data(self):
        from unittest.mock import patch
        self.post('/api/refresh', {'vehicle': 1})
        for timestamp, result in [(1704067191395, 'regression'), (None, 'time_unknown')]:
            with patch.object(FakeClient, 'status', return_value={'updateTime': timestamp}):
                self.assertEqual(self.post('/api/refresh', {'vehicle': 1})[1]['refresh_result'], result)

    def test_query_deadline_passes_through_success_and_failure(self):
        from unittest.mock import patch
        with patch.object(FakeClient, 'next_query_at', 2000000000, create=True):
            self.assertEqual(self.post('/api/refresh', {'vehicle': 1})[1]['next_query_at'], 2000000000)
            FakeClient.fail = True
            self.post('/api/refresh', {'vehicle': 1})
            self.assertEqual(self.app.state()['next_query_at'], 2000000000)

    def test_control_storage_failure_does_not_claim_success(self):
        from unittest.mock import patch
        self.post('/api/recording', {'active': False, 'interval': 60})
        with patch('zeekr_control.sampling.save', side_effect=OSError('disk unavailable')):
            self.assertEqual(self.post('/api/recording', {'active': True, 'interval': 60})[0], 500)
        self.assertFalse(self.app.state()['recording']['active'])
