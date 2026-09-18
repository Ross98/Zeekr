"""Private latest-vehicle snapshots shared by monitor and Web processes."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3


def _time(raw):
    value = raw.get('updateTime') if isinstance(raw, dict) else None
    if type(value) in (int, float) and 0 <= value <= 9999999999999:
        return int(value)
    if isinstance(value, str) and value.isdigit() and len(value) <= 13:
        return int(value)
    return None


class SnapshotStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('''CREATE TABLE IF NOT EXISTS snapshots (
            scope_key TEXT NOT NULL, vehicle_key TEXT NOT NULL, state_time INTEGER,
            fetched_at INTEGER NOT NULL, observed_at INTEGER NOT NULL,
            revision INTEGER NOT NULL, digest TEXT NOT NULL, raw TEXT NOT NULL,
            PRIMARY KEY(scope_key, vehicle_key))''')
        db.commit()
        return db

    def publish(self, scope_key, vehicle_key, raw, observed_at, fetched_at=None):
        if not all(isinstance(value, str) and value for value in (scope_key, vehicle_key)):
            raise ValueError('快照作用域或车辆无效。')
        if not isinstance(raw, dict) or type(observed_at) is not int:
            raise ValueError('车辆快照格式无效。')
        fetched_at = observed_at if fetched_at is None else fetched_at
        if type(fetched_at) is not int:
            raise ValueError('车辆读取时间无效。')
        encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        state_time = _time(raw)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state_time,revision,digest FROM snapshots WHERE scope_key=? AND vehicle_key=?',
                             (scope_key, vehicle_key)).fetchone()
            if row:
                old_time, revision, old_digest = row
                if old_time is not None and (state_time is None or state_time < old_time):
                    return {'changed': False, 'revision': revision}
                if state_time == old_time and digest == old_digest:
                    return {'changed': False, 'revision': revision}
                revision += 1
            else:
                revision = 1
            db.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?)',
                       (scope_key, vehicle_key, state_time, fetched_at, observed_at,
                        revision, digest, encoded))
            return {'changed': True, 'revision': revision}

    def read(self, scope_key, vehicle_key):
        if not self.path.exists() or not scope_key or not vehicle_key:
            return None
        with self.connect() as db:
            row = db.execute('''SELECT state_time,fetched_at,observed_at,revision,raw
                                FROM snapshots WHERE scope_key=? AND vehicle_key=?''',
                             (scope_key, vehicle_key)).fetchone()
        if not row:
            return None
        return {'state_time': row[0], 'fetched_at': row[1], 'observed_at': row[2],
                'revision': row[3], 'raw': json.loads(row[4])}


def session_scope(session):
    """Stable private scope; digest never leaves server-side storage lookups."""
    if not isinstance(session, dict):
        raise ValueError('车辆会话无效。')
    return hashlib.sha256(json.dumps(session, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
