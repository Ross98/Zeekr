"""Private, revision-checked user records with undo and recoverable deletion."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from .archive_reader import _private
from .snapshots import session_scope

COLLECTIONS = {'charges','tags','rules','experiments','expenses','reminders','place_names'}
VALID_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')


def account_scope(session):
    user = session.get('userId')
    value = 'user:'+user if isinstance(user,str) and user else 'session:'+session_scope(session)
    return hashlib.sha256(('personal-v1:'+value).encode()).hexdigest()


def _encoded(body,limit=16384):
    if not isinstance(body,dict):
        raise ValueError('记录内容无效。')
    try:
        result=json.dumps(body,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    except (ValueError,TypeError,RecursionError):
        raise ValueError('记录内容格式无效。') from None
    if len(result.encode())>limit:
        raise ValueError('记录内容过长。')
    return result


class PersonalStore:
    def __init__(self,path):
        self.path=Path(path)

    @contextmanager
    def connect(self,write=False):
        if write:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            _private(self.path.parent,directory=True)
            fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            os.close(fd)
        if not self.path.exists() and not self.path.is_symlink():
            yield None
            return
        _private(self.path.parent,directory=True);_private(self.path)
        db=sqlite3.connect(self.path.absolute().as_uri()+('' if write else '?mode=ro'),uri=True,timeout=5)
        try:
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version not in ((0,1,2) if write else (1,2)):
                raise ValueError('个人记录数据库版本不支持。')
            if write:
                with db:
                    db.execute('''CREATE TABLE IF NOT EXISTS records (
                        owner TEXT,vehicle TEXT,collection TEXT,id TEXT,body TEXT NOT NULL,
                        deleted INTEGER NOT NULL,updated_at INTEGER NOT NULL,
                        PRIMARY KEY(owner,vehicle,collection,id))''')
                    db.execute('''CREATE TABLE IF NOT EXISTS revisions (
                        owner TEXT,vehicle TEXT,collection TEXT,revision INTEGER NOT NULL,
                        PRIMARY KEY(owner,vehicle,collection))''')
                    db.execute('''CREATE TABLE IF NOT EXISTS changes (
                        owner TEXT,vehicle TEXT,collection TEXT,revision INTEGER,id TEXT,operation TEXT,previous TEXT,
                        PRIMARY KEY(owner,vehicle,collection,revision))''')
                    db.execute('''CREATE TABLE IF NOT EXISTS commute_rule_versions (
                        owner TEXT NOT NULL, vehicle TEXT NOT NULL, version INTEGER NOT NULL,
                        effective_at INTEGER NOT NULL, enabled INTEGER NOT NULL, deleted INTEGER NOT NULL,
                        home_lat REAL, home_lon REAL, home_radius INTEGER,
                        work_lat REAL, work_lon REAL, work_radius INTEGER,
                        PRIMARY KEY(owner,vehicle,version))''')
                    db.execute('''CREATE TABLE IF NOT EXISTS commute_decisions (
                        owner TEXT NOT NULL, vehicle TEXT NOT NULL, event_id TEXT NOT NULL,
                        rule_version INTEGER NOT NULL, result TEXT NOT NULL,
                        start_time INTEGER, end_time INTEGER, start_distance REAL, end_distance REAL,
                        excluded INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(owner,vehicle,event_id))''')
                    # Additive tables preserve v1 readers for release rollback.
                    db.execute('PRAGMA user_version=1')
            else:
                db.execute('PRAGMA query_only=ON')
            yield db
        finally:
            db.close()

    @staticmethod
    def _key(owner,vehicle,collection):
        if (not all(isinstance(v,str) and 0<len(v)<=256 for v in (owner,vehicle))
                or collection not in COLLECTIONS):
            raise ValueError('个人记录作用域无效。')
        return owner,vehicle,collection

    @staticmethod
    def _row(row):
        return {'id':row[0],'body':json.loads(row[1]),'deleted':bool(row[2]),'updated_at':row[3]}

    def _read(self,db,key):
        if db is None:
            return {'revision':0,'records':[],'can_undo':False}
        rev=db.execute('SELECT revision FROM revisions WHERE owner=? AND vehicle=? AND collection=?',key).fetchone()
        revision=rev[0] if rev else 0
        rows=db.execute('SELECT id,body,deleted,updated_at FROM records WHERE owner=? AND vehicle=? AND collection=? '
                        'ORDER BY updated_at DESC,id LIMIT 10001',key).fetchall()
        if len(rows)>10000:
            raise ValueError('个人记录数量超限。')
        latest=db.execute('SELECT operation FROM changes WHERE owner=? AND vehicle=? AND collection=? AND revision=?',
                          (*key,revision)).fetchone()
        return {'revision':revision,'records':[self._row(row) for row in rows],
                'can_undo':bool(latest and latest[0]!='undo')}

    def read(self,owner,vehicle,collection):
        key=self._key(owner,vehicle,collection)
        with self.connect() as db:
            if db is None:return self._read(None,key)
            db.execute('BEGIN')
            return self._read(db,key)

    def change(self,owner,vehicle,collection,action,identity,body,revision,guard=None):
        key=self._key(owner,vehicle,collection)
        if action not in ('save','delete','restore','undo') or type(revision) is not int or revision<0:
            raise ValueError('记录操作或版本无效。')
        if action!='undo' and (not isinstance(identity,str) or not VALID_ID.fullmatch(identity)):
            raise ValueError('记录编号无效。')
        body_limit=65536 if collection=='experiments' else 16384
        encoded=_encoded(body,body_limit) if action=='save' else None
        with self.connect(write=True) as db,db:
            db.execute('BEGIN IMMEDIATE')
            current=self._read(db,key)
            if current['revision']!=revision:
                raise ValueError('记录已有更新，请重新加载后再保存；填写内容仍保留。')
            prior=None
            if action=='undo':
                if not current['can_undo']:
                    raise ValueError('当前没有可撤销的操作。')
                previous=db.execute('SELECT id,previous FROM changes WHERE owner=? AND vehicle=? AND collection=? AND revision=?',
                                    (*key,revision)).fetchone()
                identity=previous[0]
                restore=json.loads(previous[1]) if previous[1] is not None else None
            row=db.execute('SELECT id,body,deleted,updated_at FROM records WHERE owner=? AND vehicle=? AND collection=? AND id=?',
                           (*key,identity)).fetchone()
            if row:prior=self._row(row)
            if action in ('delete','restore') and prior is None:
                raise ValueError('记录不存在或不属于当前车辆。')
            now=max(int(time.time()*1000),(prior['updated_at']+1) if prior else 0)
            if action=='undo':
                if restore is None:
                    db.execute('DELETE FROM records WHERE owner=? AND vehicle=? AND collection=? AND id=?',(*key,identity))
                else:
                    db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?)',
                               (*key,identity,_encoded(restore['body'],body_limit),int(restore['deleted']),now))
            elif action=='save':
                if prior is None and len(current['records'])>={'rules':100,'experiments':200,'reminders':200}.get(collection,10000):
                    raise ValueError('个人记录数量超限。')
                db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?)',(*key,identity,encoded,0,now))
            else:
                if prior['deleted']==(action=='delete'):
                    raise ValueError('记录状态已变化，请重新加载。')
                db.execute('UPDATE records SET deleted=?,updated_at=? WHERE owner=? AND vehicle=? AND collection=? AND id=?',
                           (int(action=='delete'),now,*key,identity))
            db.execute('INSERT INTO changes VALUES(?,?,?,?,?,?,?)',
                       (*key,revision+1,identity,action,json.dumps(prior,ensure_ascii=False,allow_nan=False) if prior else None))
            db.execute('INSERT OR REPLACE INTO revisions VALUES(?,?,?,?)',(*key,revision+1))
            # The interface promises one-step undo, not an unbounded audit log.
            # Keep only that step, in the same transaction as the guarded write.
            db.execute('DELETE FROM changes WHERE owner=? AND vehicle=? AND collection=? AND revision<?',
                       (*key,revision+1))
            if guard:guard()
            return self._read(db,key)

    def change_many(self, owner, vehicle, collection, action, identities, revision, guard=None):
        """Soft-delete or restore a previewed batch without offering one-step undo."""
        key = self._key(owner, vehicle, collection)
        if (action not in ('delete', 'restore') or type(revision) is not int or revision < 0
                or not isinstance(identities, list) or not 1 <= len(identities) <= 100
                or len(set(identities)) != len(identities)
                or any(not isinstance(identity, str) or not VALID_ID.fullmatch(identity) for identity in identities)):
            raise ValueError('批量记录操作或版本无效。')
        with self.connect(write=True) as db, db:
            db.execute('BEGIN IMMEDIATE')
            current = self._read(db, key)
            if current['revision'] != revision:
                raise ValueError('账本记录已有更新，请重新预览。')
            rows = db.execute('SELECT id,deleted FROM records WHERE owner=? AND vehicle=? AND collection=? '
                              'AND id IN (%s)' % ','.join('?'*len(identities)), (*key, *identities)).fetchall()
            found = {row[0]: bool(row[1]) for row in rows}
            target = action == 'delete'
            if any(identity not in found or found[identity] == target for identity in identities):
                raise ValueError('关联账单不存在、状态已变化或不属于当前车辆。')
            now = int(time.time()*1000)
            db.execute('UPDATE records SET deleted=?,updated_at=? WHERE owner=? AND vehicle=? AND collection=? '
                       'AND id IN (%s)' % ','.join('?'*len(identities)),
                       (int(target), now, *key, *identities))
            new_revision = revision+1
            # Batch changes remain recoverable from trash, but are not ambiguous one-step undo operations.
            db.execute('DELETE FROM changes WHERE owner=? AND vehicle=? AND collection=?', key)
            db.execute('INSERT OR REPLACE INTO revisions VALUES(?,?,?,?)', (*key, new_revision))
            if guard:
                guard()
            return self._read(db, key)
