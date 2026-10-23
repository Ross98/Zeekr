"""Durable single-flight credential exchange; no network inside its short lock."""
from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sqlite3
import sys
import time
import uuid

from .coordination_context import lock_context
from .credential_store import credential_store, sync_directory
from .delivery_state import delivery_lock, DeliveryBusy,add_columns
from .errors import ApiError
from .personal_store import account_scope
from .private_state import database
from .snapshots import session_scope
from .storage import load


class CredentialBusy(ApiError):
    pass


def refresh_fingerprint(session):
    token=session.get('refreshToken')
    if not isinstance(token,str) or not token.strip():
        reference=session.get('refresh_fingerprint')
        return reference if isinstance(reference,str) and re.fullmatch('[0-9a-f]{64}',reference) else None
    return hashlib.sha256(('refresh-v1\0'+account_scope(session)+'\0'+token).encode()).hexdigest()


def process_identity(pid=None):
    pid=os.getpid() if pid is None else pid
    if sys.platform=='darwin':
        from .resource_monitor import process_cpu
        birth=str(process_cpu(pid)[1])
        boot=subprocess.check_output(['/usr/sbin/sysctl','-n','kern.bootsessionuuid'],text=True,timeout=2).strip()
    elif sys.platform.startswith('linux'):
        birth=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()[19]
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    else: raise OSError('进程身份检查不可用。')
    return dict(pid=pid,birth=birth,boot=boot)


def owner_alive(owner):
    try: return process_identity(owner['pid'])==owner
    except (OSError,ValueError,subprocess.SubprocessError):
        try: os.kill(owner['pid'],0)
        except ProcessLookupError:return False
        except (PermissionError,OSError):return None
        return None


class CredentialCoordinator:
    def __init__(self,path,store=None,owner_alive=owner_alive,clock=time.time):
        self.path=Path(path)
        self.root=self.path.parent
        self.store=store if store is not None else credential_store(path)
        self.owner_alive=owner_alive
        self.clock=clock

    @contextmanager
    def locked(self):
        try:
            with lock_context('credential'),delivery_lock(self.root/'credential-coordination.lock'):
                with database(self.root/'credential-coordination.sqlite3') as db:
                    db.execute('CREATE TABLE IF NOT EXISTS credential_operations (op_id TEXT PRIMARY KEY,kind TEXT,phase TEXT,active_slot INTEGER UNIQUE,baseline TEXT,refresh_fp TEXT,owner TEXT,claimed INTEGER,expected TEXT)')
                    add_columns(db,'credential_operations',{'previous_refresh_state':'TEXT'})
                    db.execute('CREATE TABLE IF NOT EXISTS refresh_states (fingerprint TEXT PRIMARY KEY,state TEXT NOT NULL)')
                    db.execute('CREATE TABLE IF NOT EXISTS refresh_reuse_trials(id TEXT PRIMARY KEY,fingerprint TEXT,baseline TEXT,operation TEXT)')
                    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS refresh_reuse_trial_once ON refresh_reuse_trials(fingerprint)')
                    db.execute('CREATE TABLE IF NOT EXISTS refresh_reuse_contracts(fingerprint TEXT PRIMARY KEY,authorization TEXT,confirmed_scope TEXT)')
                    db.commit()
                    yield db
        except DeliveryBusy:
            raise CredentialBusy('凭据操作正在进行，请稍候。') from None
        except sqlite3.Error:
            raise ApiError('凭据协调记录不可用；未绕过保护。') from None
        except subprocess.SubprocessError:
            raise ApiError('凭据操作进程身份无法核对；未绕过保护。') from None

    def _terminal(self,db,row,phase):
        db.execute('UPDATE credential_operations SET phase=?,active_slot=NULL WHERE op_id=?',(phase,row['op_id']))
        if row['refresh_fp']:
            prior=row['previous_refresh_state'] or 'eligible'
            state=prior if phase in ('not_sent','rate_limited') else phase
            if state not in ('eligible','completed','rejected'):state='uncertain'
            db.execute('INSERT OR REPLACE INTO refresh_states VALUES (?,?)',(row['refresh_fp'],state))

    def _reconcile(self,db):
        row=db.execute('SELECT * FROM credential_operations WHERE active_slot=1').fetchone()
        if not row:return 'idle'
        owner=json.loads(row['owner'])
        alive=False if owner.get('abandoned') else self.owner_alive(owner)
        if alive is not False:return 'busy'
        current=session_scope(load(self.path))
        if row['expected'] and row['phase'] in ('prepared','activating'):
            try:
                candidate=self.store.read_staged(row['op_id'])
                valid=session_scope(candidate)==row['expected']
                if valid and current in (row['baseline'],row['expected']):
                    if current==row['baseline']:self.store.activate(row['op_id'])
                    self._terminal(db,row,'completed')
                    db.execute("UPDATE credential_operations SET phase='committed' WHERE op_id=?",(row['op_id'],))
                    return 'committed'
            except (ApiError,OSError,ValueError):
                # No new gateway request; retain staged evidence for inspection.
                self._terminal(db,row,'uncertain');return 'uncertain'
        phase='uncertain' if current==row['baseline'] else 'superseded'
        self._terminal(db,row,phase)
        return phase

    def reconcile(self):
        with self.locked() as db,db:return self._reconcile(db)

    def refresh_state(self,session):
        fingerprint=refresh_fingerprint(session)
        if not fingerprint:return 'unavailable'
        with self.locked() as db:
            row=db.execute('SELECT state FROM refresh_states WHERE fingerprint=?',(fingerprint,)).fetchone()
            return row[0] if row else 'eligible'

    @staticmethod
    def _status_success(outcome):
        return bool(outcome and outcome.operation=='status' and outcome.actual_request and not outcome.cache_hit
                    and outcome.schema_valid and outcome.success_code in ('1000','000000'))

    def _reusable(self,db,session):
        fingerprint=refresh_fingerprint(session)
        row=db.execute('SELECT c.confirmed_scope FROM refresh_reuse_contracts c JOIN refresh_states s ON s.fingerprint=c.fingerprint WHERE c.fingerprint=? AND s.state=?',(fingerprint,'completed')).fetchone()
        return bool(row and row[0]==session_scope(session))

    def reusable(self,session):
        with self.locked() as db:return self._reusable(db,session)

    def authorize_reuse(self,expected_scope):
        """Only the explicitly invoked one-trial CLI calls this; no network."""
        with self.locked() as db,db:
            session=load(self.path);fingerprint=refresh_fingerprint(session)
            state=db.execute('SELECT state FROM refresh_states WHERE fingerprint=?',(fingerprint,)).fetchone()
            if (session_scope(session)!=expected_scope or not state or state[0]!='completed'
                    or db.execute('SELECT 1 FROM credential_operations WHERE active_slot=1').fetchone()):
                raise CredentialBusy('当前状态不允许受控复用试验。')
            proof=uuid.uuid4().hex
            db.execute('INSERT INTO refresh_reuse_trials VALUES(?,?,?,NULL)',(proof,fingerprint,expected_scope))
            return proof

    def accept_reuse(self,proof,session,outcome):
        if not self._status_success(outcome):raise CredentialBusy('复用试验尚未通过实际目标状态请求。')
        with self.locked() as db,db:
            scope=session_scope(session);fingerprint=refresh_fingerprint(session)
            row=db.execute("SELECT t.fingerprint FROM refresh_reuse_trials t JOIN credential_operations o ON o.op_id=t.operation WHERE t.id=? AND o.phase='committed' AND o.expected=?",(proof,scope)).fetchone()
            if (scope!=session_scope(load(self.path)) or not row or row[0]!=fingerprint
                    or db.execute('SELECT 1 FROM credential_operations WHERE active_slot=1').fetchone()):
                raise CredentialBusy('复用试验证据与当前会话不符。')
            db.execute('INSERT OR REPLACE INTO refresh_reuse_contracts VALUES(?,?,?)',(fingerprint,proof,scope))

    def confirm_status(self,session,outcome):
        if not self._status_success(outcome):return False
        with self.locked() as db,db:
            scope=session_scope(session);fingerprint=refresh_fingerprint(session)
            if scope!=session_scope(load(self.path)):return False
            # A read can advance an existing contract's scope, never create
            # evidence or clear uncertain/rejected/executing refresh state.
            db.execute("UPDATE refresh_reuse_contracts SET confirmed_scope=? WHERE fingerprint=? AND EXISTS(SELECT 1 FROM refresh_states WHERE fingerprint=? AND state='completed')",(scope,fingerprint,fingerprint))
            return self._reusable(db,session)

    def reserve(self,kind,expected_scope,refresh_token=None,reuse_authorization=None):
        if kind not in ('refresh','sms_login','jwt_login','logout'):raise ValueError('不支持的凭据操作。')
        with self.locked() as db,db:
            self._reconcile(db)
            db.commit()
            if db.execute('SELECT 1 FROM credential_operations WHERE active_slot=1').fetchone():
                raise CredentialBusy('凭据交换正在进行，请稍候。')
            session=load(self.path)
            if session_scope(session)!=expected_scope:raise CredentialBusy('会话已更新，请使用当前会话。')
            fingerprint=None;prior=None;operation=uuid.uuid4().hex
            if kind=='refresh':
                if not refresh_token or refresh_token!=self.store.read_refresh(session):
                    raise CredentialBusy('刷新凭据未确认。')
                fingerprint=refresh_fingerprint(session)
                row=db.execute('SELECT state FROM refresh_states WHERE fingerprint=?',(fingerprint,)).fetchone()
                prior=row[0] if row else 'eligible'
                if prior!='eligible':
                    trial=False
                    if prior=='completed' and reuse_authorization:
                        trial=db.execute('UPDATE refresh_reuse_trials SET operation=? WHERE id=? AND fingerprint=? AND baseline=? AND operation IS NULL',
                            (operation,reuse_authorization,fingerprint,expected_scope)).rowcount==1
                    if not trial and not (prior=='completed' and not reuse_authorization and self._reusable(db,session)):
                        raise CredentialBusy('此刷新凭据禁止自动重放。')
                db.execute('INSERT OR REPLACE INTO refresh_states VALUES (?,?)',(fingerprint,'executing'))
            db.execute('INSERT INTO credential_operations(op_id,kind,phase,active_slot,baseline,refresh_fp,owner,claimed,expected,previous_refresh_state) VALUES (?,?,?,1,?,?,?,?,NULL,?)',
                       (operation,kind,'dispatch_planned',expected_scope,fingerprint,json.dumps(process_identity()),int(self.clock()*1000),prior))
            return operation

    def _owned(self,db,operation):
        row=db.execute('SELECT * FROM credential_operations WHERE op_id=? AND active_slot=1',(operation,)).fetchone()
        if row is None or json.loads(row['owner'])!=process_identity():
            raise CredentialBusy('凭据操作执行权已变化。')
        return row

    def suspend(self,operation):
        """The caller has stopped committing; recovery may only finish local work."""
        with self.locked() as db,db:
            row=self._owned(db,operation)
            if row['expected']:
                owner=json.loads(row['owner']);owner['abandoned']=True
                db.execute('UPDATE credential_operations SET owner=? WHERE op_id=?',(json.dumps(owner),operation))
            else:self._terminal(db,row,'uncertain')

    def finish(self,operation,phase):
        if phase not in ('not_sent','rate_limited','uncertain','rejected'):raise ValueError('凭据操作结果无效。')
        with self.locked() as db,db:
            row=self._owned(db,operation)
            self._terminal(db,row,phase)

    def prepare(self,operation,candidate):
        with self.locked() as db,db:
            row=self._owned(db,operation)
            if session_scope(load(self.path))!=row['baseline']:
                self._terminal(db,row,'superseded');return 'superseded'
            candidate=dict(candidate)
            baseline=load(self.path)
            if baseline.get('userId') and candidate.get('userId')!=baseline['userId']:
                raise ApiError('刷新响应账号不一致。')
            candidate['credential_revision']=operation
            candidate=self.store.stage(operation,candidate)
            db.execute("UPDATE credential_operations SET phase='prepared',expected=? WHERE op_id=?",(session_scope(candidate),operation))
            return 'prepared'

    def commit(self,operation,candidate):
        if self.prepare(operation,candidate)=='superseded':return 'superseded'
        with self.locked() as db,db:
            row=self._owned(db,operation)
            if session_scope(load(self.path))!=row['baseline']:
                self._terminal(db,row,'superseded');return 'superseded'
            self.store.activate(operation)
            self._terminal(db,row,'completed')
            db.execute("UPDATE credential_operations SET phase='committed' WHERE op_id=?",(operation,))
        # Remove redundant candidate secrets only after durable commit. Crash leftovers
        # are never used to repeat an exchange, and remain covered by private backup.
        try:self.store.discard(operation)
        except OSError:pass  # Redundant private staging cleanup cannot undo commit.
        return 'committed'

    def logout(self,operation):
        with self.locked() as db,db:
            row=self._owned(db,operation)
            if row['kind']!='logout' or session_scope(load(self.path))!=row['baseline']:
                self._terminal(db,row,'superseded');return 'superseded'
            self.path.unlink(missing_ok=True);sync_directory(self.root)
            self._terminal(db,row,'completed')
            return 'committed'
