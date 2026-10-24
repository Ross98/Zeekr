"""Single-flight refresh classification with synthetic gateway responses."""
from pathlib import Path
import tempfile
import unittest
from zeekr_control.client import Client
from zeekr_control.errors import ApiError, RateLimited, RequestDeferred
from zeekr_control.storage import load, save
from zeekr_control.credential_store import FileCredentialStore
from zeekr_control.refresh_recovery import RefreshDriver, RefreshPolicy

OLD=dict(accessToken='old-access',refreshToken='old-refresh',userId='user',clientId='client',deviceId='device')


class RefreshRecoveryTests(unittest.TestCase):
    def test_query_storage_failure_before_request_keeps_refresh_eligible(self):
        from zeekr_control.query_policy import QueryPolicy
        for fault in ('permissions','database'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'session.json';save(path,OLD)
                cache=path.parent/'queries.sqlite3';cache.write_bytes(b'private sentinel')
                cache.chmod(0o644 if fault=='permissions' else 0o600)
                policy=QueryPolicy(cache,clock=lambda:1000)
                driver=RefreshDriver(path,client_factory=lambda session:Client(session,self.factory(session).transport,policy),
                                     policy=RefreshPolicy(enabled=True),store=FileCredentialStore(path,allow_refresh=True))
                before=len(self.calls)
                self.assertEqual(driver.attempt(OLD,self.incident,181000).kind,'deferred')
                self.assertEqual(len(self.calls),before)
                self.assertEqual(driver.coordinator.refresh_state(OLD),'eligible')
                self.assertEqual(load(path),OLD)
                self.assertEqual(cache.read_bytes(),b'private sentinel')

    def test_unreadable_collection_controls_do_not_consume_refresh_eligibility(self):
        from zeekr_control.monitor_runtime import Runner
        from zeekr_control.query_policy import QueryPolicy
        from zeekr_control.sampling import save_settings
        root=self.path.parent
        runner=Runner.__new__(Runner);runner.root=root
        path=root/'sampling.json';path.write_text('{broken');path.chmod(0o600)
        policy=QueryPolicy(root/'queries.sqlite3',clock=lambda:1000)
        driver=RefreshDriver(self.path,client_factory=lambda session:Client(session,self.factory(session).transport,policy,
                             request_guard=runner._guard_collection_request),policy=RefreshPolicy(enabled=True),
                             store=FileCredentialStore(self.path,allow_refresh=True))
        self.assertEqual(driver.attempt(OLD,self.incident,181000).kind,'deferred')
        self.assertEqual(self.calls,[])
        self.assertEqual(load(self.path),OLD)
        self.assertEqual(driver.coordinator.refresh_state(OLD),'eligible')
        self.assertEqual(path.read_text(),'{broken')
        save_settings(root,True,30)
        self.assertEqual(driver.attempt(OLD,self.incident,182000).kind,'refreshed')
        self.assertEqual(len(self.calls),1)

    def test_cancelled_before_transport_keeps_refresh_eligible_and_session_unchanged(self):
        from zeekr_control.monitor_runtime import CollectionCancelled
        from zeekr_control.query_policy import QueryPolicy
        allowed=[False]
        def guard():
            if not allowed[0]:raise CollectionCancelled('synthetic collection paused',retry_after=1)
        policy=QueryPolicy(self.path.parent/'queries.sqlite3',clock=lambda:1000)
        driver=RefreshDriver(self.path,client_factory=lambda session:Client(session,self.factory(session).transport,policy,
                             request_guard=guard),policy=RefreshPolicy(enabled=True),store=FileCredentialStore(self.path,allow_refresh=True))
        result=driver.attempt(OLD,self.incident,181000)
        self.assertEqual(result.kind,'deferred')
        self.assertEqual(self.calls,[])
        self.assertEqual(load(self.path),OLD)
        self.assertEqual(driver.coordinator.refresh_state(OLD),'eligible')
        allowed[0]=True
        self.assertEqual(driver.attempt(OLD,self.incident,182000).kind,'refreshed')
        self.assertEqual(len(self.calls),1)

    def test_malformed_refresh_secret_never_commits_or_replays(self):
        cases=[('refreshToken',value) for value in ([],42,'bad\r\nsynthetic-secret','   ')]
        cases += [('clientId',value) for value in ([],{},False)]
        for field,value in cases:
            with self.subTest(field=field,value_type=type(value).__name__),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'session.json';save(path,OLD)
                self.response={'code':'1000','data':{'accessToken':'new-access',field:value}}
                driver=RefreshDriver(path,client_factory=self.factory,policy=RefreshPolicy(enabled=True),
                                     store=FileCredentialStore(path,allow_refresh=True))
                before=len(self.calls)
                self.assertEqual(driver.attempt(OLD,self.incident,181000).kind,'uncertain')
                self.assertEqual(load(path),OLD)
                self.assertEqual(driver.attempt(OLD,self.incident,999000).kind,'manual_required')
                self.assertEqual(len(self.calls),before+1)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'session.json';save(self.path,OLD)
        self.calls=[]
        self.response={'code':'1000','data':{'accessToken':'new-access','refreshToken':'new-refresh'}}
        def wire(*args):
            self.calls.append(args)
            if isinstance(self.response,Exception):raise self.response
            return self.response
        self.factory=lambda session:Client(session,wire)
        self.driver=RefreshDriver(self.path,client_factory=self.factory,policy=RefreshPolicy(enabled=True),store=FileCredentialStore(self.path,allow_refresh=True))
        self.incident=dict(attempts=3,opened_at=1000)

    def run_refresh(self,now=181000):return self.driver.attempt(load(self.path),self.incident,now)

    def test_disabled_and_threshold_do_not_issue_refresh(self):
        disabled=RefreshDriver(self.path,client_factory=self.factory)
        self.assertEqual(disabled.attempt(OLD,self.incident,181000).kind,'disabled')
        self.assertEqual(self.run_refresh(2000).kind,'waiting')
        self.assertEqual(self.calls,[])

    def test_refresh_secrets_never_enter_query_cache(self):
        from zeekr_control.query_policy import QueryPolicy
        policy=QueryPolicy(self.path.parent/'queries.sqlite3')
        client=Client(OLD,self.factory(OLD).transport,policy)
        client.refresh_gw2(OLD['refreshToken'])
        blob=policy.path.read_bytes()
        for secret in ('old-refresh','new-refresh','old-access','new-access'):
            self.assertNotIn(secret.encode(),blob)

    def test_refresh_preserves_remaining_status_interval_and_default_is_protected(self):
        from zeekr_control.query_policy import QueryPolicy
        policy=QueryPolicy(self.path.parent/'queries.sqlite3',clock=lambda:1000)
        def failed_status():raise ApiError('1509',gateway_code='1509')
        with self.assertRaises(ApiError):policy.run('user','old-access','status','car',failed_status)
        factory=lambda session:Client(session,self.factory(session).transport,policy)
        driver=RefreshDriver(self.path,client_factory=factory,policy=RefreshPolicy(enabled=True),store=FileCredentialStore(self.path,allow_refresh=True))
        self.assertEqual(driver.attempt(OLD,self.incident,181000).kind,'refreshed')
        with self.assertRaises(RequestDeferred):factory(load(self.path)).status('L6T79X2Z0NP000001')
        self.assertEqual(len(self.calls),1)
        default=RefreshDriver(self.path)
        self.assertIsInstance(default.client_factory(OLD).query_policy,QueryPolicy)

    def test_success_is_only_refresh_complete_and_reentrant_old_baseline_skips(self):
        self.assertEqual(self.run_refresh().kind,'refreshed')
        self.assertEqual(load(self.path)['accessToken'],'new-access')
        self.assertEqual(self.driver.attempt(OLD,self.incident,182000).kind,'superseded')
        self.assertEqual(len(self.calls),1)

    def test_uncertain_and_rejected_keep_access_and_never_replay_same_refresh(self):
        for error,state in [(ApiError('网络或 TLS 连接失败'),'uncertain'),(OSError('synthetic response lost'),'uncertain'),(ApiError('网关 HTTP 401',http_status=401),'manual_required')]:
            with self.subTest(state=state):
                with tempfile.TemporaryDirectory() as folder:
                    path=Path(folder)/'session.json';save(path,OLD)
                    driver=RefreshDriver(path,client_factory=self.factory,policy=RefreshPolicy(enabled=True),store=FileCredentialStore(path,allow_refresh=True))
                    self.response=error;before=len(self.calls)
                    self.assertEqual(driver.attempt(OLD,self.incident,181000).kind,state)
                    self.assertEqual(driver.attempt(OLD,self.incident,999000).kind,'manual_required')
                    self.assertEqual(len(self.calls),before+1)
                    self.assertEqual(load(path),OLD)

    def test_deferred_and_rate_limit_keep_eligibility(self):
        from zeekr_control.query_policy import QueryPolicy
        import sqlite3
        policy=QueryPolicy(self.path.parent/'queries.sqlite3',clock=lambda:1000)
        policy.run('user','old-access','login','',lambda:{})
        with sqlite3.connect(policy.path) as db:
            db.execute("INSERT INTO cooldown VALUES ('gateway',1090)")
        driver=RefreshDriver(self.path,client_factory=lambda session:Client(session,self.factory(session).transport,policy),
                             policy=RefreshPolicy(enabled=True),store=FileCredentialStore(self.path,allow_refresh=True))
        result=driver.attempt(OLD,self.incident,181000)
        self.assertEqual(result.kind,'deferred');self.assertEqual(result.wait_seconds,90)
        self.assertEqual(self.calls,[])
        self.assertEqual(driver.coordinator.refresh_state(OLD),'eligible')
        self.response=RateLimited(120)
        self.assertEqual(self.run_refresh().kind,'rate_limited')
        self.assertEqual(self.driver.coordinator.refresh_state(OLD),'eligible')
        self.assertEqual(load(self.path),OLD)

    def test_storage_failure_does_not_repeat_gateway_exchange(self):
        from unittest.mock import patch
        with patch.object(self.driver.coordinator.store,'activate',side_effect=OSError('private-token')):
            self.assertEqual(self.run_refresh().kind,'storage_error')
        self.assertEqual(self.driver.coordinator.reconcile(),'committed')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(load(self.path)['accessToken'],'new-access')
