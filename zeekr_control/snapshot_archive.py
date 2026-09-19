"""Private full-response history, partitioned by Beijing calendar year/month.

Payloads are losslessly compressed and deduplicated; every distinct successful
read retains its own observation/fetch times. No deletion or public raw-data API.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import os
from pathlib import Path
import sqlite3
import stat


BEIJING = timezone(timedelta(hours=8))
MAX_TIMESTAMP = 9999999999999


def validate_timestamp(value):
    if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP:
        raise ValueError('归档采集时间无效。')


def _private_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OSError('归档目录权限不安全，应由服务用户持有且权限为 700。')
    finally:
        os.close(fd)


class SnapshotArchive:
    def __init__(self, root):
        self.root = Path(root)

    def append(self, scope_key, vehicle_key, encoded, state_time, observed_at,
               fetched_at, source='unknown'):
        validate_timestamp(observed_at)
        validate_timestamp(fetched_at)
        if source not in ('unknown', 'monitor', 'manual'):
            raise ValueError('归档读取来源无效。')
        date = datetime.fromtimestamp(observed_at / 1000, BEIJING)
        # Monthly shards avoid a whole year's payloads hitting service file-size
        # limits. The enclosing directory is the calendar-year archive unit.
        self.root.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        for directory in (self.root.parent, self.root, self.root / str(date.year)):
            _private_directory(directory)
        path = self.root / str(date.year) / ('%02d.sqlite3' % date.month)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise OSError('归档文件权限不安全，应由服务用户持有且权限为 600。')
        finally:
            os.close(fd)
        payload = encoded.encode('utf-8')
        digest = hashlib.sha256(payload).hexdigest()
        compressed = gzip.compress(payload, mtime=0)
        with closing(sqlite3.connect(path, timeout=10)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                db.execute('BEGIN IMMEDIATE')
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, 1):
                    raise sqlite3.DatabaseError('不支持的归档版本。')
                db.execute('''CREATE TABLE IF NOT EXISTS payloads (
                    digest TEXT PRIMARY KEY, encoding TEXT NOT NULL,
                    raw_bytes INTEGER NOT NULL, compressed_json BLOB NOT NULL)''')
                db.execute('''CREATE TABLE IF NOT EXISTS reads (
                    id INTEGER PRIMARY KEY, scope_key TEXT NOT NULL, vehicle_key TEXT NOT NULL,
                    state_time INTEGER, fetched_at INTEGER NOT NULL, observed_at INTEGER NOT NULL,
                    source TEXT NOT NULL, digest TEXT NOT NULL REFERENCES payloads(digest),
                    UNIQUE(scope_key,vehicle_key,observed_at,fetched_at,source,digest))''')
                db.execute('CREATE INDEX IF NOT EXISTS reads_vehicle_time ON reads(vehicle_key,state_time)')
                db.execute('PRAGMA user_version=1')
                db.execute('INSERT OR IGNORE INTO payloads VALUES (?,?,?,?)',
                           (digest, 'gzip-json-v1', len(payload), compressed))
                db.execute('''INSERT OR IGNORE INTO reads
                    (scope_key,vehicle_key,state_time,fetched_at,observed_at,source,digest)
                    VALUES (?,?,?,?,?,?,?)''',
                           (scope_key, vehicle_key, state_time, fetched_at, observed_at, source, digest))
