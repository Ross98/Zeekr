"""Background request cancellation uses synthetic clients and private temp data."""
from contextlib import contextmanager,ExitStack
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from zeekr_control.client import Client
from zeekr_control.monitor_runtime import Runner
from zeekr_control.query_policy import QueryPolicy
from zeekr_control.delivery_state import delivery_lock,DeliveryBusy
from zeekr_control.sampling import save_settings
from zeekr_control.storage import save
from test_monitor import BASE,sample


class CollectionRequestGuardTests(unittest.TestCase):
    def test_unsafe_query_cache_is_not_an_account_block(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stop=threading.Event();wire=Mock(side_effect=self.response)
            path=root/'queries.sqlite3';path.write_bytes(b'private sentinel');path.chmod(0o644)
            with self.offline_runner(root,wire,stop) as (runner,clients):
                runner.tick(BASE)
                wire.assert_not_called()
                self.assertIsNone(runner.blocked_fingerprint)
                self.assertEqual(runner.health()['status'],'cooldown')
                self.assertEqual(path.read_bytes(),b'private sentinel')

    @staticmethod
    def response(method,url,headers,body):
        return ({'code':'1000','data':{'list':[{'vin':'L6T79X2Z0NP000001'}]}}
                if '/device-platform/' in url else {'code':'1000','data':{'vehicleStatus':sample(0)}})

    @contextmanager
    def offline_runner(self,root,wire,stop,clock=None):
        save(root/'session.json',{'accessToken':'synthetic-access','userId':'synthetic-user'})
        clients=[];initialize=Client.__init__
        def initialize_offline(client,*args,**kwargs):
            kwargs['transport']=wire;kwargs['query_policy'].clock=clock or (lambda:BASE/1000)
            initialize(client,*args,**kwargs);clients.append(client)
        runner=Runner(root/'session.json',sender=Mock(),alert_sender=Mock());runner.stop=stop
        try:
            with patch.object(Client,'__init__',initialize_offline):yield runner,clients
        finally:runner.insight_worker.close()

    def test_control_file_failure_during_query_lock_is_not_an_auth_failure(self):
        for fault in ('json','interval','permissions','enabled'):
            for phase in (1,2):
                with self.subTest(fault=fault,phase=phase),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);stop=threading.Event();locks=[0];now=[BASE/1000]
                    wire=Mock(side_effect=self.response);original=QueryPolicy._request_lock
                    @contextmanager
                    def corrupted(policy):
                        with original(policy):
                            locks[0]+=1
                            if locks[0]==phase:
                                path=root/'sampling.json'
                                if fault=='json':path.write_text('{broken');path.chmod(0o600)
                                elif fault=='interval':save(path,{'enabled':'true','interval':'broken'})
                                elif fault=='enabled':save(path,{'enabled':'broken','interval':'30'})
                                else:save_settings(root,True);path.chmod(0o644)
                            yield
                    with self.offline_runner(root,wire,stop,clock=lambda:now[0]) as (runner,clients):
                        with patch.object(QueryPolicy,'_request_lock',corrupted):runner.tick(BASE)
                        self.assertEqual(wire.call_count,phase-1)
                        self.assertEqual(runner.health()['status'],'unavailable')
                        self.assertIn('采集配置',runner.health()['error'])
                        self.assertEqual(runner.health()['gap_pending'],'true')
                        self.assertIsNone(runner.blocked_fingerprint)
                        with runner.auth_failure_alert.connect() as db:
                            self.assertEqual(db.execute('SELECT COUNT(*) FROM auth_outbox').fetchone()[0],0)
                        self.assertFalse(clients[0].query_outcome.actual_request)
                        save_settings(root,True,30);now[0]+=30
                        runner.tick(BASE+30000)
                        self.assertEqual(wire.call_count,2)
                        self.assertEqual(runner.health()['status'],'fresh')

    def test_stop_or_pause_while_acquiring_query_lock_prevents_new_transport(self):
        for mode in ('stop','pause'):
            for phase in (1,2):
                with self.subTest(mode=mode,phase=phase),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);stop=threading.Event();locks=[0];wire=Mock(side_effect=self.response)
                    original=QueryPolicy._request_lock
                    @contextmanager
                    def changed_during_lock(policy):
                        with original(policy):
                            locks[0]+=1
                            if locks[0]==phase:
                                if mode=='stop':stop.set()
                                else:save_settings(root,False)
                            yield
                    with self.offline_runner(root,wire,stop) as (runner,clients):
                        with patch.object(QueryPolicy,'_request_lock',changed_during_lock):runner.tick(BASE)
                        self.assertEqual(wire.call_count,phase-1)
                        self.assertEqual(runner.health()['status'],'stopped' if mode=='stop' else 'paused')
                        self.assertIsNone(runner.blocked_fingerprint)
                        runner.alert_sender.assert_not_called()
                        self.assertFalse(clients[0].query_outcome.actual_request)

    def test_real_query_lock_wait_rechecks_cancellation_after_acquisition(self):
        for mode in ('stop','pause'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);stop=threading.Event();waiting=threading.Event();wire=Mock(side_effect=self.response)
                @contextmanager
                def observed_lock(path):
                    with ExitStack() as stack:
                        try:stack.enter_context(delivery_lock(path))
                        except DeliveryBusy:waiting.set();raise
                        yield
                with self.offline_runner(root,wire,stop) as (runner,clients),\
                     patch('zeekr_control.query_policy.delivery_lock',observed_lock),\
                     ThreadPoolExecutor(max_workers=1) as pool:
                    with delivery_lock(root/'queries.sqlite3.lock'):
                        result=pool.submit(runner.tick,BASE)
                        self.assertTrue(waiting.wait(2),'query never encountered the held lock')
                        if mode=='stop':stop.set()
                        else:save_settings(root,False)
                    result.result(timeout=3)
                    wire.assert_not_called()
                    self.assertEqual(runner.health()['status'],'stopped' if mode=='stop' else 'paused')

    def test_valid_inflight_status_is_retained_when_pause_or_stop_arrives(self):
        for mode in ('stop','pause'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);stop=threading.Event()
                def transport(method,url,headers,body):
                    if '/remote-control/' in url:
                        if mode=='stop':stop.set()
                        else:save_settings(root,False)
                    return self.response(method,url,headers,body)
                wire=Mock(side_effect=transport)
                with self.offline_runner(root,wire,stop) as (runner,clients):
                    runner.tick(BASE)
                    self.assertEqual(wire.call_count,2)
                    self.assertEqual(runner.health()['status'],'fresh')
                    binding=runner.analysis_input[1]
                    self.assertEqual(runner.monitor.status(binding)['last']['time'],BASE)
                    self.assertTrue(clients[0].query_outcome.actual_request)
                    self.assertTrue(clients[0].query_outcome.schema_valid)
                    runner.alert_sender.assert_not_called()

    def test_manual_client_without_background_guard_still_reads_while_paused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);save_settings(root,False);wire=Mock(side_effect=self.response)
            client=Client({'accessToken':'synthetic-access','userId':'synthetic-user'},transport=wire,
                          query_policy=QueryPolicy(root/'queries.sqlite3',clock=lambda:BASE/1000))
            self.assertEqual(client.status('L6T79X2Z0NP000001'),sample(0))
            wire.assert_called_once()
