"""Refresh secrets in user Keychain; references in legacy-compatible session."""
import hashlib
import re
from .credential_store import FileCredentialStore
from .errors import ApiError
from .macos_keychain import MacKeychain


class KeychainCredentialStore(FileCredentialStore):
    def __init__(self,path,keychain=None):
        super().__init__(path,allow_refresh=True)
        self.keychain=keychain
        self.prefix=hashlib.sha256(str(self.path.absolute()).encode()).hexdigest()+'-'

    def backend(self):
        if self.keychain is None:self.keychain=MacKeychain()
        return self.keychain

    def read_refresh(self,session):
        reference=session.get('refresh_ref')
        if not reference:return None
        if not isinstance(reference,str) or not re.fullmatch(re.escape(self.prefix)+'[0-9a-f]{32}',reference):
            raise ApiError('钥匙串引用不属于本数据目录。')
        token=self.backend().get(reference)
        from .credential_coordinator import refresh_fingerprint
        if refresh_fingerprint(dict(session,refreshToken=token))!=session.get('refresh_fingerprint'):
            raise ApiError('钥匙串凭据指纹不一致。')
        return token

    def stage(self,operation,session):
        self._candidate(operation)
        session=dict(session)
        token=session.pop('refreshToken',None)
        if token:
            from .credential_coordinator import refresh_fingerprint
            reference=self.prefix+operation
            self.backend().put(reference,token)
            # Verify noninteractive access before making even a staged pointer.
            if self.backend().get(reference)!=token:raise ApiError('钥匙串候选核对失败。')
            session.update(refresh_ref=reference,refresh_fingerprint=refresh_fingerprint(dict(session,refreshToken=token)))
        elif session.get('refresh_ref'):self.read_refresh(session)
        return super().stage(operation,session)

    def read_staged(self,operation):
        session=super().read_staged(operation)
        if session.get('refreshToken'):raise ApiError('拒绝明文刷新凭据候选。')
        self.read_refresh(session)
        return session
