"""Cross-process request serialization, private short-lived cache and cooldown.

SQLite's write transaction stays held during the request, so independent CLI
and Web processes cannot send requests concurrently from this local profile.
"""
from contextlib import closing
from datetime import timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import time

from .errors import ApiError, RateLimited

DEFAULT_PATH = Path.home() / 'Library' / 'Application Support' / 'ZeekrControl' / 'queries.sqlite3'
INTERVAL = 60


def retry_seconds(value, now=None):
    now = time.time() if now is None else now
    try:
        if value is not None and value.strip().isdigit():
            return max(1, int(value.strip()))
        target = parsedate_to_datetime(value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max(1, math.ceil(target.timestamp() - now))
    except (TypeError, ValueError, OverflowError, AttributeError):
        return INTERVAL


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class QueryPolicy:
    def __init__(self, path=DEFAULT_PATH, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.cache_hit = False
        self.fetched_at = None
        self.next_query_at = None

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent = self.path.parent.stat()
        if self.path.parent.is_symlink() or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise ApiError('查询缓存目录必须由当前用户持有，权限为 700。')
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ApiError('查询缓存文件必须由当前用户持有，权限为 600。')
        finally:
            os.close(fd)
        connection = sqlite3.connect(str(self.path), timeout=25, isolation_level=None)
        return connection

    def run(self, account, session, operation, resource, fetch):
        # Only hashes go into keys. Responses can contain location/VIN; the
        # database is private plaintext, not a credential vault.
        account_key = digest(account)
        cache_key = digest(json.dumps([account, session, operation, resource]))
        self.cache_hit, self.fetched_at, self.next_query_at = False, None, None
        try:
            with closing(self._connect()) as connection:
                connection.execute('BEGIN IMMEDIATE')
                try:
                    connection.execute('CREATE TABLE IF NOT EXISTS cooldown (key TEXT PRIMARY KEY, until REAL NOT NULL)')
                    connection.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, fetched REAL NOT NULL, expires REAL NOT NULL, data TEXT NOT NULL)')
                    now = self.clock()
                    connection.execute('DELETE FROM cache WHERE expires <= ?', (now,))
                    keys = ['gateway'] + (['status:' + account_key] if operation == 'status' else [])
                    deadlines = [connection.execute('SELECT until FROM cooldown WHERE key=?', (key,)).fetchone() for key in keys]
                    self.next_query_at = max([now] + [row[0] for row in deadlines if row])
                    row = connection.execute('SELECT fetched, data FROM cache WHERE key=?', (cache_key,)).fetchone()
                    if row and 0 <= now - row[0] < INTERVAL:
                        self.cache_hit, self.fetched_at = True, row[0]
                        self.next_query_at = max(self.next_query_at, row[0] + INTERVAL)
                        result = json.loads(row[1])
                        connection.commit()
                        return result
                    # A 429 pauses every gateway and login operation in this
                    # local profile. Valid cached results remain readable.
                    for key in keys:
                        row = connection.execute('SELECT until FROM cooldown WHERE key=?', (key,)).fetchone()
                        if row and row[0] > now:
                            raise ApiError('本机查询保护：请等待 %d 秒后再查询；未发送网络请求。' % math.ceil(row[0] - now))
                    if operation == 'status':
                        self.next_query_at = max(self.next_query_at, now + INTERVAL)
                        connection.execute('INSERT OR REPLACE INTO cooldown VALUES (?, ?)', ('status:' + account_key, now + INTERVAL))
                    try:
                        result = fetch()
                    except RateLimited as exc:
                        gateway_until = self.clock() + exc.seconds
                        self.next_query_at = max(self.next_query_at, gateway_until)
                        connection.execute('INSERT OR REPLACE INTO cooldown VALUES (?, ?)', ('gateway', gateway_until))
                        connection.commit()
                        raise
                    except Exception:
                        # Preserve the status-attempt interval even on failure.
                        connection.commit()
                        raise
                    self.fetched_at = self.clock()
                    if operation in ('status', 'vehicles'):
                        self.next_query_at = max(self.next_query_at, self.fetched_at + INTERVAL)
                        connection.execute('INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?)',
                                           (cache_key, self.fetched_at, self.fetched_at + INTERVAL,
                                            json.dumps(result, ensure_ascii=False, allow_nan=False)))
                    connection.commit()
                    return result
                finally:
                    if connection.in_transaction:
                        connection.rollback()
        except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError):
            raise ApiError('查询缓存或并发锁不可用；未绕过保护，请稍后重试。') from None
