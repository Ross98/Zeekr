"""Synthetic credentials only; no official gateway, SMS or keychain."""
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from zeekr_control.storage import load, save
from zeekr_control.snapshots import session_scope
from zeekr_control.credential_coordinator import CredentialCoordinator, CredentialBusy
from zeekr_control.credential_store import FileCredentialStore

OLD=dict(accessToken='synthetic-old',refreshToken='synthetic-refresh',userId='synthetic-user',clientId='client',deviceId='device')
NEW=dict(OLD,accessToken='synthetic-new',refreshToken='synthetic-next')


def compete(path,start,release,results):
    store=FileCredentialStore(Path(path),allow_refresh=True)
    coordinator=CredentialCoordinator(Path(path),store=store)
    start.wait(5)
    try:
        op=coordinator.reserve('refresh',session_scope(OLD),OLD['refreshToken'])
        from zeekr_control.client import Client
        def transport(*args):
            results.put('request');release.wait(5)
            return {'code':'1000','data':{'accessToken':NEW['accessToken'],'refreshToken':NEW['refreshToken']}}
        candidate=Client(OLD,transport).refresh_gw2(OLD['refreshToken'])
        coordinator.commit(op,candidate)
    except CredentialBusy: results.put('busy')


def crash_after_response(path):
    coordinator=CredentialCoordinator(Path(path),store=FileCredentialStore(path,allow_refresh=True))
    coordinator.reserve('refresh',session_scope(OLD),OLD['refreshToken'])
    from zeekr_control.client import Client
    Client(OLD,lambda *args:{'code':'1000','data':NEW}).refresh_gw2(OLD['refreshToken'])
    os._exit(23)  # Gateway succeeded, but no candidate or completion was saved.


class CredentialCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'private/session.json';save(self.path,OLD)
        self.store=FileCredentialStore(self.path,allow_refresh=True)
        self.c=CredentialCoordinator(self.path,store=self.store)

    def reserve(self): return self.c.reserve('refresh',session_scope(load(self.path)),load(self.path)['refreshToken'])

    def test_active_owner_not_stolen_and_manual_login_waits(self):
        op=self.reserve()
        self.assertEqual(self.c.reconcile(),'busy')
        with self.assertRaises(CredentialBusy): self.c.reserve('sms_login',session_scope(OLD))
        self.c.finish(op,'uncertain')
        self.assertEqual(self.c.refresh_state(OLD),'uncertain')
        self.assertIsNotNone(self.c.reserve('sms_login',session_scope(OLD)))

    def test_success_and_same_refresh_does_not_rearm(self):
        op=self.reserve();self.c.commit(op,dict(NEW,refreshToken=OLD['refreshToken']))
        self.assertEqual(load(self.path)['accessToken'],NEW['accessToken'])
        self.assertEqual(self.c.refresh_state(load(self.path)),'completed')
        with self.assertRaises(CredentialBusy): self.reserve()

    def test_reuse_requires_one_time_authority_then_actual_status_confirmation(self):
        from zeekr_control.client import QueryOutcome
        op=self.reserve();self.c.commit(op,dict(NEW,refreshToken=OLD['refreshToken']))
        active=load(self.path)
        proof=self.c.authorize_reuse(session_scope(active))
        op=self.c.reserve('refresh',session_scope(active),OLD['refreshToken'],reuse_authorization=proof)
        self.c.commit(op,dict(NEW,refreshToken=OLD['refreshToken']))
        newer=load(self.path)
        self.assertFalse(self.c.reusable(newer))
        cached=QueryOutcome(operation='status',cache_hit=True,schema_valid=True,success_code='1000')
        with self.assertRaises(CredentialBusy):self.c.accept_reuse(proof,newer,cached)
        good=QueryOutcome(operation='status',actual_request=True,schema_valid=True,success_code='1000')
        self.c.accept_reuse(proof,newer,good)
        self.assertTrue(self.c.reusable(newer))
        op=self.c.reserve('refresh',session_scope(newer),OLD['refreshToken'])
        self.c.commit(op,dict(NEW,refreshToken=OLD['refreshToken']))
        newest=load(self.path)
        self.assertFalse(self.c.reusable(newest))
        with self.assertRaises(CredentialBusy):self.c.reserve('refresh',session_scope(newest),OLD['refreshToken'])
        self.c.confirm_status(newest,good)
        self.assertTrue(self.c.reusable(newest))
        op=self.c.reserve('refresh',session_scope(newest),OLD['refreshToken']);self.c.finish(op,'uncertain')
        self.c.confirm_status(newest,good)
        self.assertFalse(self.c.reusable(newest))
        with self.assertRaises(CredentialBusy):self.c.authorize_reuse(session_scope(newest))

    def test_reuse_trial_cannot_be_replayed_or_turn_cooldown_into_eligibility(self):
        op=self.reserve();self.c.commit(op,dict(NEW,refreshToken=OLD['refreshToken']))
        active=load(self.path);proof=self.c.authorize_reuse(session_scope(active))
        op=self.c.reserve('refresh',session_scope(active),OLD['refreshToken'],reuse_authorization=proof)
        self.c.finish(op,'rate_limited')
        self.assertEqual(self.c.refresh_state(active),'completed')
        with self.assertRaises(CredentialBusy):self.c.reserve('refresh',session_scope(active),OLD['refreshToken'],reuse_authorization=proof)

    def test_new_refresh_is_eligible_and_no_secret_in_journal(self):
        op=self.reserve();self.c.commit(op,NEW)
        self.assertEqual(self.c.refresh_state(load(self.path)),'eligible')
        blob=(self.path.parent/'credential-coordination.sqlite3').read_bytes()
        for secret in (OLD['accessToken'],OLD['refreshToken'],NEW['accessToken'],NEW['refreshToken']):
            self.assertNotIn(secret.encode(),blob)

    def test_uncertainty_survives_new_access_and_restart(self):
        op=self.reserve();self.c.finish(op,'uncertain')
        save(self.path,dict(OLD,accessToken='different-access'))
        c=CredentialCoordinator(self.path,store=self.store)
        self.assertEqual(c.refresh_state(load(self.path)),'uncertain')
        with self.assertRaises(CredentialBusy): c.reserve('refresh',session_scope(load(self.path)),OLD['refreshToken'])

    def test_dead_owner_without_candidate_becomes_uncertain_and_releases_claim(self):
        op=self.reserve()
        c=CredentialCoordinator(self.path,store=self.store,owner_alive=lambda owner:False)
        self.assertEqual(c.reconcile(),'uncertain')
        self.assertEqual(c.refresh_state(OLD),'uncertain')
        self.assertIsNotNone(c.reserve('sms_login',session_scope(OLD)))

    def test_prepared_and_activated_crash_windows_roll_forward_without_network(self):
        for activate in (False,True):
            with self.subTest(activate=activate):
                save(self.path,OLD)
                op=self.c.reserve('sms_login',session_scope(OLD))
                self.c.prepare(op,NEW)
                if activate: self.store.activate(op)
                c=CredentialCoordinator(self.path,store=self.store,owner_alive=lambda owner:False)
                self.assertEqual(c.reconcile(),'committed')
                self.assertEqual(load(self.path)['accessToken'],NEW['accessToken'])

    def test_external_update_never_overwritten(self):
        op=self.reserve();self.c.prepare(op,NEW)
        other=dict(OLD,accessToken='external-update');save(self.path,other)
        self.assertEqual(self.c.commit(op,NEW),'superseded')
        self.assertEqual(load(self.path),other)

    def test_deferred_request_restores_eligibility_and_logout_cannot_resurrect(self):
        op=self.reserve();self.c.finish(op,'not_sent')
        self.assertEqual(self.c.refresh_state(OLD),'eligible')
        op=self.c.reserve('logout',session_scope(OLD));self.c.logout(op)
        self.assertEqual(load(self.path),{})
        with self.assertRaises(CredentialBusy): self.c.commit(op,NEW)

    def test_unknown_owner_is_not_taken_over(self):
        self.reserve()
        c=CredentialCoordinator(self.path,store=self.store,owner_alive=lambda owner:None)
        self.assertEqual(c.reconcile(),'busy')

    def test_reused_pid_is_not_mistaken_for_original_owner(self):
        from unittest.mock import patch
        from zeekr_control.credential_coordinator import owner_alive
        old=dict(pid=123,birth='original',boot='boot')
        with patch('zeekr_control.credential_coordinator.process_identity',return_value=dict(old,birth='new')):
            self.assertIs(owner_alive(old),False)

    def test_unavailable_process_identity_fails_closed_with_safe_error(self):
        from unittest.mock import patch
        import subprocess
        from zeekr_control.errors import ApiError
        with patch('zeekr_control.credential_coordinator.process_identity',side_effect=subprocess.TimeoutExpired('sysctl',2)):
            with self.assertRaisesRegex(ApiError,'进程身份'):
                self.reserve()
        self.assertEqual(load(self.path),OLD)
        self.assertEqual(self.c.refresh_state(OLD),'eligible')

    def test_default_store_refuses_refresh_secret_persistence(self):
        c=CredentialCoordinator(self.path)
        op=c.reserve('sms_login',session_scope(OLD))
        with self.assertRaises(ValueError): c.commit(op,NEW)
        self.assertEqual(load(self.path),OLD)

    def test_multiprocess_gateway_call_is_single_flight(self):
        ctx=multiprocessing.get_context('spawn')
        start,release,results=ctx.Event(),ctx.Event(),ctx.Queue()
        processes=[ctx.Process(target=compete,args=(str(self.path),start,release,results)) for _ in range(2)]
        for process in processes: process.start()
        try:
            start.set()
            self.assertEqual(sorted([results.get(timeout=10),results.get(timeout=10)]),['busy','request'])
        finally:
            release.set()
            for process in processes:
                process.join(10)
                if process.is_alive():process.kill();process.join()
        self.assertTrue(all(p.exitcode==0 for p in processes))

    def test_real_process_exit_after_gateway_success_never_replays(self):
        ctx=multiprocessing.get_context('spawn')
        process=ctx.Process(target=crash_after_response,args=(str(self.path),))
        process.start();process.join(10)
        if process.is_alive():process.kill();process.join()
        self.assertEqual(process.exitcode,23)
        restarted=CredentialCoordinator(self.path,store=self.store)
        self.assertEqual(restarted.reconcile(),'uncertain')
        self.assertEqual(load(self.path),OLD)
        with self.assertRaises(CredentialBusy):
            restarted.reserve('refresh',session_scope(OLD),OLD['refreshToken'])
        self.assertIsNotNone(restarted.reserve('sms_login',session_scope(OLD)))

    def test_lock_order_rejects_nesting_and_secrets_have_private_permissions(self):
        from zeekr_control.coordination_context import lock_context
        with lock_context('query'):
            with self.assertRaises(RuntimeError):self.reserve()
        with self.c.locked():
            with self.assertRaises(RuntimeError):
                with lock_context('query'):pass
        op=self.reserve();self.c.prepare(op,NEW)
        for path in (self.path,self.store._candidate(op),self.path.parent/'credential-coordination.sqlite3'):
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.store.directory.stat().st_mode & 0o777,0o700)
