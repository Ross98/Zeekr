"""Atomic candidate storage. Refresh secret persistence requires explicit opt-in.

Default legacy mode handles existing read credentials only. No keychain choice
or real refresh-token capture is made by instantiating this store.
"""
from pathlib import Path
import os
import re
from .storage import load, save


def sync_directory(path):
    fd=os.open(path,os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


class FileCredentialStore:
    def __init__(self,path,allow_refresh=False):
        self.path=Path(path)
        self.allow_refresh=allow_refresh
        self.directory=self.path.parent/'credential-staging'

    def read_refresh(self,session):return session.get('refreshToken') if self.allow_refresh else None

    def _candidate(self,operation):
        if not isinstance(operation,str) or not re.fullmatch('[0-9a-f]{32}',operation):
            raise ValueError('凭据操作编号无效。')
        return self.directory/(operation+'.json')

    def stage(self,operation,session):
        if not isinstance(session,dict) or any(not isinstance(v,str) for v in session.values()):
            raise ValueError('候选凭据格式无效。')
        if not self.allow_refresh and session.get('refreshToken'):
            raise ValueError('尚未授权刷新凭据存储。')
        path=self._candidate(operation)
        save(path,session);sync_directory(path.parent);sync_directory(self.path.parent)
        return session

    def read_staged(self,operation):
        return load(self._candidate(operation))

    def activate(self,operation):
        candidate=self.read_staged(operation)
        if not candidate.get('accessToken') or not candidate.get('userId'):
            raise ValueError('候选凭据未完成，不能激活。')
        if not self.allow_refresh and candidate.get('refreshToken'):
            raise ValueError('尚未授权刷新凭据存储。')
        save(self.path,candidate);sync_directory(self.path.parent)

    def discard(self,operation):
        path=self._candidate(operation)
        if path.exists():path.unlink();sync_directory(path.parent)


class UnavailableCredentialStore(FileCredentialStore):
    """Keep read-only collection constructible; deny every credential write."""
    def stage(self,*args):
        from .errors import ApiError
        raise ApiError('凭据存储配置不可用；未回退其他存储。')


def credential_store(path):
    from .errors import ApiError
    try:policy=load(Path(path).parent/'connection-policy.json')
    except (ApiError,OSError):return UnavailableCredentialStore(path)
    if policy.get('token_provider')=='keychain':
        from .keychain_store import KeychainCredentialStore
        return KeychainCredentialStore(path)
    if policy.get('token_provider') not in (None,'unselected'):
        return UnavailableCredentialStore(path)
    return FileCredentialStore(path)


def login_candidate(client,store):
    candidate=dict(client.session)
    token=getattr(client,'login_refresh_token',None)
    if store.allow_refresh and isinstance(token,str) and token.strip():candidate['refreshToken']=token
    return candidate
