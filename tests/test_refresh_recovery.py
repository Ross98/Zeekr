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
        for error,state in [(ApiError('网络或 TLS 连接失败'),'uncertain'),(ApiError('网关 HTTP 401',http_status=401),'manual_required')]:
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
