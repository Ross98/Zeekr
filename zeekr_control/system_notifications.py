"""Durable authentication-outage intent; collection never performs network I/O."""
from contextlib import contextmanager
import sqlite3
import time

from .archive_reader import _private
from .sqlite_files import prepare_database_file
from .delivery_state import delivery_lock, add_columns
from .notifications import DeliveryError, bark_time
from .storage import load


class AuthFailureAlert:
    def __init__(self,root,sender=None):
        self.root=root;self.sender=sender;self.path=root/'system-notifications.sqlite3'

    @contextmanager
    def connect(self):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        _private(self.root,directory=True)
        prepare_database_file(self.path)
        _private(self.path)
        db=sqlite3.connect(self.path,timeout=5)
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS auth_state(id INTEGER PRIMARY KEY,generation INTEGER,active INTEGER)')
                db.execute('CREATE TABLE IF NOT EXISTS auth_outbox(generation INTEGER PRIMARY KEY,created INTEGER,state TEXT,error TEXT,sent_at INTEGER)')
                db.execute('CREATE TABLE IF NOT EXISTS auth_outbox_context(generation INTEGER PRIMARY KEY,kind TEXT)')
                add_columns(db,'auth_outbox_context',{'incident_id':'TEXT','reason':'TEXT'})
                db.execute('CREATE UNIQUE INDEX IF NOT EXISTS auth_context_incident ON auth_outbox_context(incident_id,kind)')
                if db.execute('SELECT 1 FROM auth_state WHERE id=1').fetchone() is None:
                    legacy=load(self.root/'auth-failure-alert.json').get('state')
                    db.execute('INSERT INTO auth_state VALUES(1,0,?)',(int(legacy in ('sending','sent','failed','uncertain')),))
            yield db
        finally:db.close()

    def record_failure(self, code, reason, now):
        # Only the client's already-sanitized scalar reason enters this bounded audit.
        with self.connect() as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS gateway_failures(id INTEGER PRIMARY KEY,created INTEGER,code TEXT,reason TEXT)')
            db.execute('INSERT INTO gateway_failures(created,code,reason) VALUES(?,?,?)', (now,code,(reason or '')[:240]))
            db.execute('DELETE FROM gateway_failures WHERE id NOT IN (SELECT id FROM gateway_failures ORDER BY id DESC LIMIT 200)')

    def blocked(self,error,now=None,manual=False,incident_id=None,reason=None):
        if '网关代码 1509' not in error:return
        now=int(time.time()*1000) if now is None else now
        with self.connect() as db,db:
            db.execute('BEGIN IMMEDIATE')
            alert_kind='manual' if manual else 'interruption'
            if incident_id and db.execute('SELECT 1 FROM auth_outbox_context WHERE incident_id=? AND kind=?',
                                         (incident_id,alert_kind)).fetchone():return
            generation,active=db.execute('SELECT generation,active FROM auth_state WHERE id=1').fetchone()
            if active:
                kind=db.execute('SELECT kind FROM auth_outbox_context WHERE generation=?',(generation,)).fetchone()
                if not manual or kind and kind[0]=='manual':return
                db.execute("UPDATE auth_outbox SET state='cancelled' WHERE state IN ('pending','preparing')")
            generation+=1
            db.execute('UPDATE auth_state SET generation=?,active=1 WHERE id=1',(generation,))
            db.execute("INSERT INTO auth_outbox VALUES(?,?,'pending',NULL,NULL)",(generation,now))
            # Owner requested original gateway wording in private Bark notifications.
            reason = (reason[:240].encode('utf-8','backslashreplace').decode('utf-8')[:240]
                      if isinstance(reason,str) else '')
            db.execute('INSERT INTO auth_outbox_context(generation,kind,incident_id,reason) VALUES(?,?,?,?)',
                       (generation,alert_kind,incident_id,reason))

    def recovered(self):
        if not self.path.exists() and not (self.root/'auth-failure-alert.json').exists():return
        with self.connect() as db,db:
            db.execute('UPDATE auth_state SET active=0 WHERE id=1')
            db.execute("UPDATE auth_outbox SET state='cancelled' WHERE state IN ('pending','preparing')")

    def deliver(self,guard=None):
        if self.sender is None or not self.path.exists():return
        with delivery_lock(self.root/'notifications.lock'):
            with self.connect() as db,db:
                db.execute("UPDATE auth_outbox SET state='uncertain',error='send_interrupted' WHERE state='sending'")
                db.execute("UPDATE auth_outbox SET state='cancelled' WHERE state IN ('pending','preparing') "
                           'AND NOT EXISTS (SELECT 1 FROM auth_state WHERE active=1 AND generation=auth_outbox.generation)')
                db.execute("UPDATE auth_outbox SET state='pending',error='prepare_interrupted' WHERE state='preparing'")
                rows=db.execute("SELECT generation FROM auth_outbox WHERE state='pending' ORDER BY generation LIMIT 1").fetchall()
            for generation, in rows:
                if guard:guard()
                with self.connect() as db,db:
                    claimed=db.execute("UPDATE auth_outbox SET state='preparing' WHERE generation=? AND state='pending' "
                        'AND EXISTS (SELECT 1 FROM auth_state WHERE active=1 AND generation=auth_outbox.generation)',(generation,)).rowcount
                if not claimed:continue
                try:
                    last = load(self.root/'monitor-health.json').get('last_success')
                    body = '采集暂未恢复，后台仍在自动重试。期间轨迹与行程可能不完整。'
                    with self.connect() as db:
                        context=db.execute('SELECT kind,reason FROM auth_outbox_context WHERE generation=?',(generation,)).fetchone()
                    if context and context[0]=='manual':
                        body='自动续期未能确认，采集仍在受保护重试。请人工核对车辆账号连接，必要时重新认证；不确定的刷新请求不会自动重放。'
                    reason = context[1] if context and context[1] else '网关未提供具体原因'
                    body = '网关代码：1509\n网关说明：' + reason + '\n' + body
                    if last: body += '\n最后成功读取：' + bark_time(last)
                except Exception:
                    with self.connect() as db,db:
                        db.execute("UPDATE auth_outbox SET state='failed',error='prepare_failed' WHERE generation=? AND state='preparing'",(generation,))
                    continue
                try:
                    if guard:guard()
                except Exception:
                    with self.connect() as db,db:
                        db.execute("UPDATE auth_outbox SET state='pending' WHERE generation=? AND state='preparing'",(generation,))
                    raise
                with self.connect() as db,db:
                    claimed=db.execute("UPDATE auth_outbox SET state='sending',error=NULL WHERE generation=? AND state='preparing' "
                        'AND EXISTS (SELECT 1 FROM auth_state WHERE active=1 AND generation=auth_outbox.generation)',(generation,)).rowcount
                if not claimed:continue
                try:
                    self.sender('⚠️ 极氪采集已中断',body)
                    state,error='sent',None
                except DeliveryError as exc:
                    state,error=('uncertain','result_unknown') if exc.ambiguous else ('failed','send_rejected')
                except Exception:state,error='uncertain','result_unknown'
                with self.connect() as db,db:
                    db.execute("UPDATE auth_outbox SET state=?,error=?,sent_at=? WHERE generation=? AND state='sending'",
                        (state,error,int(time.time()*1000) if state=='sent' else None,generation))
