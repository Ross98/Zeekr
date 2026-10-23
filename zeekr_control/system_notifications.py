"""Durable authentication-outage intent; collection never performs network I/O."""
from contextlib import contextmanager
import sqlite3
import time

from .archive_reader import _private
from .delivery_state import delivery_lock
from .notifications import DeliveryError, bark_time
from .storage import load


class AuthFailureAlert:
    def __init__(self,root,sender=None):
        self.root=root;self.sender=sender;self.path=root/'system-notifications.sqlite3'

    @contextmanager
    def connect(self):
        import os
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        _private(self.root,directory=True)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
        _private(self.path)
        db=sqlite3.connect(self.path,timeout=5)
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS auth_state(id INTEGER PRIMARY KEY,generation INTEGER,active INTEGER)')
                db.execute('CREATE TABLE IF NOT EXISTS auth_outbox(generation INTEGER PRIMARY KEY,created INTEGER,state TEXT,error TEXT,sent_at INTEGER)')
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

    def blocked(self,error,now=None):
        if '网关代码 1509' not in error:return
        now=int(time.time()*1000) if now is None else now
        with self.connect() as db,db:
            db.execute('BEGIN IMMEDIATE')
            generation,active=db.execute('SELECT generation,active FROM auth_state WHERE id=1').fetchone()
            if active:return
            generation+=1
            db.execute('UPDATE auth_state SET generation=?,active=1 WHERE id=1',(generation,))
            db.execute("INSERT INTO auth_outbox VALUES(?,?,'pending',NULL,NULL)",(generation,now))

    def recovered(self):
        if not self.path.exists() and not (self.root/'auth-failure-alert.json').exists():return
        with self.connect() as db,db:
            db.execute('UPDATE auth_state SET active=0 WHERE id=1')
            db.execute("UPDATE auth_outbox SET state='cancelled' WHERE state='pending'")

    def deliver(self,guard=None):
        if self.sender is None or not self.path.exists():return
        with delivery_lock(self.root/'notifications.lock'):
            with self.connect() as db,db:
                db.execute("UPDATE auth_outbox SET state='uncertain',error='send_interrupted' WHERE state='sending'")
                rows=db.execute("SELECT generation FROM auth_outbox WHERE state='pending' ORDER BY generation LIMIT 1").fetchall()
            for generation, in rows:
                if guard:guard()
                with self.connect() as db,db:
                    claimed=db.execute("UPDATE auth_outbox SET state='sending' WHERE generation=? AND state='pending'",(generation,)).rowcount
                if not claimed:continue
                try:
                    last = load(self.root/'monitor-health.json').get('last_success')
                    body = '车辆接口持续返回 1509，采集暂未恢复，后台仍在自动重试。期间轨迹与行程可能不完整；请查看采集状态与脱敏网关说明。'
                    if last: body += '\n最后成功读取：' + bark_time(last)
                    self.sender('⚠️ 极氪采集已中断',body)
                    state,error='sent',None
                except DeliveryError as exc:
                    state,error=('uncertain','result_unknown') if exc.ambiguous else ('failed','send_rejected')
                except Exception:state,error='uncertain','result_unknown'
                with self.connect() as db,db:
                    db.execute("UPDATE auth_outbox SET state=?,error=?,sent_at=? WHERE generation=? AND state='sending'",
                        (state,error,int(time.time()*1000) if state=='sent' else None,generation))
