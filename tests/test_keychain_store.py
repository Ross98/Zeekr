"""Synthetic keychain; never reads the user's real items."""
from pathlib import Path
import tempfile
import unittest
from zeekr_control.storage import load,save
from zeekr_control.errors import ApiError
from zeekr_control.snapshots import session_scope
from zeekr_control.credential_coordinator import CredentialCoordinator
from zeekr_control.keychain_store import KeychainCredentialStore


class FakeKeychain:
    def __init__(self):self.items={};self.locked=False
    def put(self,account,value):
        if self.locked:raise ApiError('钥匙串不可用。')
        if account in self.items and self.items[account]!=value:raise ApiError('引用冲突。')
        self.items[account]=value
    def get(self,account):
        if self.locked:raise ApiError('钥匙串不可用。')
        if account not in self.items:raise ApiError('钥匙串项目缺失。')
        return self.items[account]


class KeychainStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'private/session.json'
        self.old=dict(accessToken='synthetic-access',userId='owner',clientId='client',deviceId='device')
        save(self.path,self.old)
        self.keychain=FakeKeychain()
        self.store=KeychainCredentialStore(self.path,keychain=self.keychain)
        self.c=CredentialCoordinator(self.path,store=self.store)
        self.new=dict(self.old,accessToken='new-access',refreshToken='synthetic-refresh-secret')

    def test_commit_has_only_reference_and_reloads_refresh(self):
        op=self.c.reserve('sms_login',session_scope(self.old));self.c.commit(op,self.new)
        active=load(self.path)
        self.assertNotIn('refreshToken',active)
        self.assertEqual(self.store.read_refresh(active),self.new['refreshToken'])
        self.assertEqual(self.c.refresh_state(active),'eligible')
        for path in self.path.parent.rglob('*'):
            if path.is_file():self.assertNotIn(b'synthetic-refresh-secret',path.read_bytes())

    def test_locked_missing_or_foreign_reference_never_falls_back(self):
        op=self.c.reserve('sms_login',session_scope(self.old));self.c.commit(op,self.new)
        active=load(self.path);self.keychain.locked=True
        with self.assertRaises(ApiError):self.store.read_refresh(active)
        self.keychain.locked=False
        with self.assertRaises(ApiError):self.store.read_refresh(dict(active,refresh_ref='foreign'))
        self.keychain.items.clear()
        with self.assertRaises(ApiError):self.store.read_refresh(active)
        self.assertEqual(load(self.path),active)

    def test_crash_rollforward_and_same_refresh_stays_consumed(self):
        op=self.c.reserve('sms_login',session_scope(self.old));self.c.prepare(op,self.new)
        dead=CredentialCoordinator(self.path,store=self.store,owner_alive=lambda owner:False)
        self.assertEqual(dead.reconcile(),'committed')
        active=load(self.path)
        op=dead.reserve('refresh',session_scope(active),self.store.read_refresh(active))
        dead.commit(op,dict(self.new,accessToken='another-access'))
        self.assertEqual(dead.refresh_state(load(self.path)),'completed')

    def test_stage_failure_preserves_active_and_login_without_refresh_is_supported(self):
        op=self.c.reserve('sms_login',session_scope(self.old));self.keychain.locked=True
        with self.assertRaises(ApiError):self.c.commit(op,self.new)
        self.assertEqual(load(self.path),self.old)
        self.c.finish(op,'uncertain');self.keychain.locked=False
        op=self.c.reserve('sms_login',session_scope(self.old));self.c.commit(op,self.old)
        self.assertIsNone(self.store.read_refresh(load(self.path)))

    def test_invalid_provider_disables_writes_without_breaking_read_session(self):
        from zeekr_control.credential_store import credential_store
        save(self.path.parent/'connection-policy.json',dict(token_provider='unknown'))
        store=credential_store(self.path)
        self.assertFalse(store.allow_refresh)
        self.assertEqual(load(self.path),self.old)
        with self.assertRaises(ApiError):store.stage('a'*32,self.new)
