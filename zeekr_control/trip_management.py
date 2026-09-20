"""Reversible, previewed trip exclusion. Raw events and samples are retained."""
import hashlib
import json
import secrets
import sqlite3
import threading
import time

from .archive_reader import _private
from .events import _cursor, _decode
from .tracks import day_bounds, valid_timestamp
from .trip_visibility import has_trash, revision
from .trips import _summary
from .usage_events import UsageEvents, VALID_ID, MAX_SUMMARY_BYTES, MAX_SCAN


class TripRecordManager(UsageEvents):
    def __init__(self, path, clock=time.time):
        super().__init__(path)
        self.clock, self.plans, self.lock = clock, {}, threading.RLock()

    def revision(self, vehicle):
        with self.connect() as db:
            return revision(db, vehicle)

    @staticmethod
    def _select(db):
        removed = ('(SELECT removed_at FROM trip_record_trash t WHERE t.vehicle=e.vehicle AND t.event_id=e.id)'
                   if has_trash(db) else 'NULL')
        return (f'SELECT e.id,e.created,e.delivery,CASE WHEN length(CAST(e.summary AS BLOB))<={MAX_SUMMARY_BYTES} '
                f'THEN e.summary END,length(CAST(e.summary AS BLOB)),{removed} FROM monitor_events e ')

    @staticmethod
    def _public(row):
        identity, created, delivery, encoded, size, removed = row
        try:
            summary = json.loads(encoded)
            if not isinstance(summary, dict):
                summary = {}
        except (TypeError, ValueError, RecursionError):
            summary = {}
        item = _summary(summary, identity, 'ended')
        valid_end = valid_timestamp(item['end_time'])
        for field in ('start_time','end_time'):
            if not valid_timestamp(item[field]):
                item[field] = None
        item.update(recorded_at=created, removed_at=removed,
                    date_source='end_time' if valid_end else 'recorded_at',
                    issue='' if valid_end else '结束时间或摘要无效，按记录时间归期。')
        return item

    @staticmethod
    def _fingerprint(row):
        return hashlib.sha256(json.dumps(row, separators=(',', ':')).encode()).hexdigest()

    def query(self, vehicle, start, end, status='active', cursor=None, limit=20):
        lower, upper = day_bounds(start)[0], day_bounds(end)[1]
        if (not vehicle or status not in ('active','trash') or lower >= upper or upper-lower > 366*86400000
                or type(limit) is not int or not 1 <= limit <= 100):
            raise ValueError('请选择有效日期范围（最多 366 天）和记录状态。')
        boundary = _decode(cursor) if cursor else None
        selected = []
        with self.connect() as db:
            if db is None:
                return {'items': [], 'next_cursor': None, 'revision': 0}
            db.execute('BEGIN')
            current_revision = revision(db, vehicle)
            sql = self._select(db)+"WHERE e.vehicle=? AND e.kind='trip_end'"
            args = [vehicle]
            if boundary:
                sql += ' AND (e.created,e.id)<(?,?)'
                args.extend(boundary)
            if has_trash(db):
                sql += (' AND EXISTS' if status == 'trash' else ' AND NOT EXISTS')
                sql += ' (SELECT 1 FROM trip_record_trash t WHERE t.vehicle=e.vehicle AND t.event_id=e.id)'
            elif status == 'trash':
                return {'items': [], 'next_cursor': None, 'revision': current_revision}
            rows = db.execute(sql+' ORDER BY e.created DESC,e.id DESC LIMIT ?', args+[MAX_SCAN+1])
            for scanned, row in enumerate(rows, 1):
                if scanned > MAX_SCAN:
                    raise ValueError('行程历史过大，需先建立归期索引。')
                if not isinstance(row[0], str) or not VALID_ID.fullmatch(row[0]) or row[0] == 'current':
                    continue
                item = self._public(row)
                stamp = item['end_time'] if item['date_source']=='end_time' else item['recorded_at']
                if type(stamp) not in (int,float) or not lower <= stamp < upper:
                    continue
                selected.append(item)
                if len(selected) > limit:
                    break
        page = selected[:limit]
        next_cursor = _cursor(page[-1]['recorded_at'], page[-1]['id']) if len(selected)>limit else None
        return {'items': page, 'next_cursor': next_cursor, 'revision': current_revision}

    def _checked_rows(self, db, vehicle, identities, action):
        if db is None:
            raise ValueError('本地行程不存在。')
        rows = []
        sql = self._select(db)+"WHERE e.vehicle=? AND e.id=? AND e.kind='trip_end'"
        for identity in identities:
            row = db.execute(sql, (vehicle, identity)).fetchone()
            if row is None or (row[5] is not None) != (action == 'restore'):
                raise ValueError('行程不存在、状态已变化或不属于当前车辆，请重新读取。')
            if row[2] == 'sending':
                raise ValueError('所选行程正在发送通知，请稍后重新预览。')
            if row[4] > MAX_SUMMARY_BYTES:
                raise ValueError('所选行程摘要过大，暂不能通过网页管理。')
            # Keep only a digest and safe projection, never a batch of raw reports.
            rows.append((self._fingerprint(row), self._public(row)))
        return rows

    def preview(self, vehicle, action, identities, expected_revision, owner):
        if (not isinstance(vehicle,str) or not vehicle or not isinstance(owner,str) or not owner
                or action not in ('trash','restore') or type(expected_revision) is not int
                or not isinstance(identities,list) or not 1 <= len(identities) <= 100
                or any(not isinstance(i,str) or not VALID_ID.fullmatch(i) or i=='current' for i in identities)
                or len(set(identities)) != len(identities)):
            raise ValueError('请选择 1 至 100 条已结束行程及有效操作。')
        with self.connect() as db:
            if db is not None:
                db.execute('BEGIN')
            if revision(db, vehicle) != expected_revision:
                raise ValueError('行程记录已变化，请重新读取后选择。')
            rows = self._checked_rows(db, vehicle, identities, action)
        with self.lock:
            now = self.clock()
            self.plans = {key: plan for key,plan in self.plans.items() if plan['expires'] > now}
            while len(self.plans) >= 32:
                self.plans.pop(next(iter(self.plans)))
            token = secrets.token_urlsafe(32)
            self.plans[token] = {'vehicle': vehicle, 'action': action, 'ids': list(identities),
                                 'owner': owner, 'revision': expected_revision, 'expires': now+300,
                                 'fingerprints': [row[0] for row in rows]}
        return {'token': token, 'action': action, 'items': [row[1] for row in rows],
                'count': len(rows), 'revision': expected_revision, 'expires_at': int((now+300)*1000)}

    @staticmethod
    def _schema(db):
        db.execute('CREATE TABLE IF NOT EXISTS trip_record_trash (vehicle TEXT NOT NULL,event_id TEXT NOT NULL,removed_at INTEGER NOT NULL,PRIMARY KEY(vehicle,event_id))')
        db.execute('CREATE TABLE IF NOT EXISTS trip_record_revisions (vehicle TEXT PRIMARY KEY,revision INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS trip_record_audit (id INTEGER PRIMARY KEY,vehicle TEXT NOT NULL,revision INTEGER NOT NULL,action TEXT NOT NULL,event_ids TEXT NOT NULL,created INTEGER NOT NULL)')

    def execute(self, token, owner, guard=None):
        with self.lock:
            plan = self.plans.get(token) if isinstance(token,str) else None
            if not plan or plan['owner'] != owner or self.clock() >= plan['expires']:
                raise ValueError('预览已过期或不属于当前会话，请重新预览。')
            del self.plans[token]
        _private(self.path.parent, directory=True)
        _private(self.path)
        db = sqlite3.connect(self.path.absolute().as_uri()+'?mode=rw', uri=True, timeout=5)
        try:
            db.execute('BEGIN IMMEDIATE')
            if revision(db, plan['vehicle']) != plan['revision']:
                raise ValueError('行程记录已变化，请重新读取并预览。')
            rows = self._checked_rows(db, plan['vehicle'], plan['ids'], plan['action'])
            if [row[0] for row in rows] != plan['fingerprints']:
                raise ValueError('所选行程已变化，本次操作取消，请重新预览。')
            self._schema(db)
            now = int(self.clock()*1000)
            for identity in plan['ids']:
                if plan['action'] == 'trash':
                    db.execute('INSERT INTO trip_record_trash VALUES (?,?,?)', (plan['vehicle'],identity,now))
                    db.execute("UPDATE monitor_events SET delivery='cancelled',error='行程已移入回收区，未发送。',next_attempt=0 WHERE vehicle=? AND id=? AND delivery='pending'",
                               (plan['vehicle'],identity))
                else:
                    db.execute('DELETE FROM trip_record_trash WHERE vehicle=? AND event_id=?', (plan['vehicle'],identity))
            new_revision = plan['revision']+1
            db.execute('INSERT OR REPLACE INTO trip_record_revisions VALUES (?,?)', (plan['vehicle'],new_revision))
            db.execute('INSERT INTO trip_record_audit(vehicle,revision,action,event_ids,created) VALUES (?,?,?,?,?)',
                       (plan['vehicle'],new_revision,plan['action'],json.dumps(plan['ids']),now))
            db.execute('DELETE FROM trip_record_audit WHERE vehicle=? AND id NOT IN (SELECT id FROM trip_record_audit WHERE vehicle=? ORDER BY id DESC LIMIT 1000)',
                       (plan['vehicle'],plan['vehicle']))
            if guard:
                guard()
            db.commit()
            return {'action': plan['action'], 'count': len(plan['ids']), 'revision': new_revision}
        finally:
            db.close()
