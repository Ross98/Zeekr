"""Authorized one-shot validation orchestration using synthetic transport only."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zeekr_control.client import Client
from zeekr_control.connection_setup import configure,enable,validate,validate_reuse
from zeekr_control.credential_coordinator import CredentialCoordinator
from zeekr_control.keychain_store import KeychainCredentialStore
from zeekr_control.errors import ApiError
from zeekr_control.snapshots import session_scope
from zeekr_control.storage import load,save
from test_keychain_store import FakeKeychain


class ConnectionSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'private/session.json'
        self.session=dict(accessToken='old-access',userId='owner',clientId='client',deviceId='device')
        save(self.path,self.session)
        self.store=KeychainCredentialStore(self.path,keychain=FakeKeychain())
        c=CredentialCoordinator(self.path,store=self.store)
        op=c.reserve('sms_login',session_scope(self.session));c.commit(op,dict(self.session,refreshToken='old-refresh'))
        save(self.path.parent/'connection-policy.json',dict(schema_version='1',token_provider='keychain',auto_refresh_enabled='false'))
        import hashlib
        save(self.path.parent/'monitor-binding.json',dict(vehicle_key=hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest()))
        self.puts=0;self.refresh_value='new-refresh'
        def wire(method,url,*args):
            if method=='PUT':
                self.puts+=1
                return dict(code='1000',data=dict(accessToken='new-access',refreshToken=self.refresh_value))
            if '/status/' in url:return dict(code='1000',data={'basicVehicleStatus':{'speed':0}})
            return dict(code='1000',data={'list':[{'vin':'L6T79X2Z0NP000001'}]})
        self.factory=lambda session,**kwargs:Client(session,transport=wire,**kwargs)

    def test_real_validation_gate_requires_network_status_and_remains_disabled(self):
        from zeekr_control.refresh_recovery import RefreshDriver
        driver=lambda path,**kwargs:RefreshDriver(path,client_factory=self.factory,**kwargs)
        with patch('zeekr_control.connection_setup.credential_store',return_value=self.store),patch('zeekr_control.connection_setup.RefreshDriver',side_effect=driver),patch('zeekr_control.connection_setup.Client',side_effect=self.factory):
            result=validate(self.path)
        self.assertEqual(self.puts,1)
        self.assertEqual(result['target_status_verified'],'true')
        self.assertEqual(result['new_refresh_token'],'true')
        self.assertEqual(load(self.path.parent/'connection-policy.json')['auto_refresh_enabled'],'false')
        with patch('zeekr_control.connection_setup.probe',return_value={}):enable(self.path)
        self.assertEqual(load(self.path.parent/'connection-policy.json')['auto_refresh_enabled'],'true')

    def test_interrupted_validation_intent_never_issues_another_refresh(self):
        save(self.path.parent/'connection-validation.json',dict(refresh_result='dispatch_planned'))
        with patch('zeekr_control.connection_setup.credential_store',return_value=self.store),patch('zeekr_control.connection_setup.RefreshDriver') as driver:
            with self.assertRaises(ApiError):validate(self.path)
        driver.assert_not_called()

    def test_separately_authorized_trial_and_status_allow_reuse_but_never_repeat_trial(self):
        from zeekr_control.refresh_recovery import RefreshDriver
        self.refresh_value='old-refresh'
        def driver(path,**kwargs):
            kwargs.setdefault('store',self.store)
            return RefreshDriver(path,client_factory=self.factory,**kwargs)
        coordinator=lambda path:CredentialCoordinator(path,store=self.store)
        with patch('zeekr_control.connection_setup.credential_store',return_value=self.store),patch('zeekr_control.connection_setup.RefreshDriver',side_effect=driver),patch('zeekr_control.connection_setup.Client',side_effect=self.factory),patch('zeekr_control.connection_setup.CredentialCoordinator',side_effect=coordinator),patch('zeekr_control.connection_setup.QueryPolicy',return_value=None):
            self.assertEqual(validate(self.path)['new_refresh_token'],'false')
            self.assertEqual(validate_reuse(self.path)['reuse_verified'],'true')
            with self.assertRaises(ApiError):validate_reuse(self.path)
            with patch('zeekr_control.connection_setup.probe',return_value={}):enable(self.path)
        self.assertEqual(self.puts,2)
        self.assertEqual(load(self.path.parent/'connection-policy.json')['auto_refresh_enabled'],'true')

    def test_enabling_rejects_cache_incomplete_validation_or_changed_session(self):
        for receipt in ({},{'target_status_verified':'false'}, {'target_status_verified':'true','new_refresh_token':'false'},
                        {'target_status_verified':'true','new_refresh_token':'true','verified_scope':'other'}):
            save(self.path.parent/'connection-validation.json',receipt)
            with self.assertRaises(ApiError):enable(self.path)
        self.assertEqual(load(self.path.parent/'connection-policy.json')['auto_refresh_enabled'],'false')

    def test_configuration_does_not_replace_provider_during_exchange(self):
        c=CredentialCoordinator(self.path,store=self.store)
        c.reserve('sms_login',session_scope(load(self.path)))
        with patch('zeekr_control.connection_setup.sys.platform','darwin'):
            with self.assertRaises(ApiError):configure(self.path)
