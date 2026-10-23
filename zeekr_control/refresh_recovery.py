"""Conservative refresh scheduling. Disabled until a secret provider is selected."""
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from .client import Client
from .credential_coordinator import CredentialCoordinator, CredentialBusy
from .errors import ApiError, RateLimited, RequestDeferred
from .query_policy import QueryPolicy
from .snapshots import session_scope
from .storage import load


@dataclass(frozen=True)
class RefreshPolicy:
    enabled: bool = False
    minimum_failures: int = 3
    minimum_seconds: int = 180

    @classmethod
    def read(cls,root):
        try:
            data=load(Path(root)/'connection-policy.json')
            # Provider selection and real validation remain a separate activation
            # gate. Default driver has no refresh-capable provider at all.
            if (data.get('schema_version')!='1' or data.get('auto_refresh_enabled')!='true'
                    or data.get('token_provider') not in ('file','keychain')
                    or not data.get('validated_contract_id')):return cls()
            failures=int(data.get('refresh_after_failures','3'))
            seconds=int(data.get('refresh_after_seconds','180'))
            if not 3<=failures<=100 or not 180<=seconds<=86400:return cls()
            return cls(True,failures,seconds)
        except (ApiError,OSError,ValueError):return cls()


@dataclass(frozen=True)
class RefreshResult:
    kind: str
    wait_seconds: int = 0


class RefreshDriver:
    def __init__(self,path,client_factory=None,policy=None,store=None):
        self.path=Path(path)
        self.client_factory=client_factory if client_factory is not None else (
            lambda session:Client(session,query_policy=QueryPolicy(self.path.parent/'queries.sqlite3')))
        self.policy=policy if policy is not None else RefreshPolicy.read(self.path.parent)
        self.coordinator=CredentialCoordinator(path,store=store)

    def attempt(self,session,incident,now,reuse_authorization=None):
        if not self.policy.enabled or not self.coordinator.store.allow_refresh:
            return RefreshResult('disabled')
        if (not incident or incident['attempts']<self.policy.minimum_failures
                or now-incident['opened_at']<self.policy.minimum_seconds*1000):return RefreshResult('waiting')
        operation=None
        try:
            self.coordinator.reconcile()
            if session_scope(load(self.path))!=session_scope(session):return RefreshResult('superseded')
            state=self.coordinator.refresh_state(session)
            if state=='unavailable':return RefreshResult('disabled')
            if state in ('uncertain','rejected'):return RefreshResult('manual_required')
            if state=='completed' and not reuse_authorization and not self.coordinator.reusable(session):return RefreshResult('manual_required')
            token=self.coordinator.store.read_refresh(session)
            operation=self.coordinator.reserve('refresh',session_scope(session),token,reuse_authorization=reuse_authorization)
            client=self.client_factory(session)
            try:
                candidate=client.refresh_gw2(token)
            except RequestDeferred as exc:
                if getattr(getattr(client,'query_outcome',None),'actual_request',True):
                    self.coordinator.finish(operation,'uncertain')
                    return RefreshResult('uncertain')
                self.coordinator.finish(operation,'not_sent')
                return RefreshResult('deferred',exc.retry_after or 1)
            except RateLimited as exc:
                self.coordinator.finish(operation,'rate_limited')
                return RefreshResult('rate_limited',exc.seconds)
            except ApiError as exc:
                rejected=exc.http_status==401
                self.coordinator.finish(operation,'rejected' if rejected else 'uncertain')
                return RefreshResult('manual_required' if rejected else 'uncertain')
            except Exception:
                self.coordinator.finish(operation,'uncertain')
                return RefreshResult('uncertain')
            result=self.coordinator.commit(operation,candidate)
            return RefreshResult('refreshed' if result=='committed' else 'superseded')
        except CredentialBusy:
            return RefreshResult('busy')
        except (ApiError,OSError,ValueError,sqlite3.Error):
            if operation is not None:
                try:self.coordinator.suspend(operation)
                except (ApiError,OSError,ValueError,sqlite3.Error):pass
            return RefreshResult('storage_error')
