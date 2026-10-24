"""Cross-process request serialization, private short-lived cache and cooldown.

SQLite's write transaction stays held during the request, so independent CLI
and Web processes cannot send requests concurrently from this local profile.
"""
from contextlib import closing, contextmanager, ExitStack
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

from .errors import ApiError, RateLimited, RequestDeferred
from .coordination_context import lock_context
from .sampling import read_request_settings
from .delivery_state import delivery_lock, DeliveryBusy
from .sqlite_files import prepare_database_file

DEFAULT_PATH = Path.home() / 'Library' / 'Application Support' / 'ZeekrControl' / 'queries.sqlite3'
INTERVAL = 60
MAX_CACHE_BYTES = 4 * 1024 * 1024


def _finite_float(value):
    number=float(value)
    if not math.isfinite(number):raise ValueError('non-finite cache value')
    return number


def _reject_constant(value):
    raise ValueError('non-finite cache value')


def _decode_cache(encoded):
    if not isinstance(encoded,str) or not encoded:raise ValueError('unavailable cache payload')
    return json.loads(encoded,parse_float=_finite_float,parse_constant=_reject_constant)


def retry_seconds(value, now=None):
    now = time.time() if now is None else now
    try:
        if value is not None and value.strip().isdigit():
            wait=max(1,int(value.strip()))
        else:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            wait=max(1,math.ceil(target.timestamp()-now))
        deadline=now+wait
        if not math.isfinite(deadline) or not math.isfinite(deadline*1000):
            raise ValueError('retry deadline cannot be represented')
        return wait
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

    @contextmanager
    def _request_lock(self):
        # Keep concurrent callers waiting for the shared result even while the
        # status reservation is committed before transport begins.
        deadline=time.monotonic()+25
        with ExitStack() as stack:
            while True:
                try:stack.enter_context(delivery_lock(self.path.with_name(self.path.name+'.lock')))
                except DeliveryBusy:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise RequestDeferred('查询并发锁暂不可用；未发送网络请求。',retry_after=30) from None
                    time.sleep(min(.02,remaining))
                else:break
            yield

    def _resume_status(self,connection,account_key,attempted,interval):
        connection.execute('BEGIN IMMEDIATE')
        # Legacy callers may use only SQLite locking and run between the two
        # transactions. Their 429 or newer reservation must still take priority.
        now=self.clock()
        gateway=connection.execute("SELECT until FROM cooldown WHERE key='gateway'").fetchone()
        attempt=connection.execute('SELECT attempted FROM status_attempts WHERE key=?',(account_key,)).fetchone()
        status=connection.execute('SELECT until FROM cooldown WHERE key=?',('status:'+account_key,)).fetchone()
        deadlines=[row[0] for row in (gateway,status) if row]
        if attempt:deadlines.append(attempt[0]+interval)
        self.next_query_at=max([self.next_query_at,now]+deadlines)
        changed=not attempt or attempt[0]!=attempted
        extended=status and status[0]>attempted+interval and status[0]>now
        if changed or extended or gateway and gateway[0]>now:
            wait=max(1,math.ceil(self.next_query_at-now))
            raise RequestDeferred('本机查询保护已更新：请等待 %d 秒后再查询；未发送网络请求。'%wait,retry_after=wait)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent = self.path.parent.stat()
        if self.path.parent.is_symlink() or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise RequestDeferred('查询缓存目录必须由当前用户持有，权限为 700。',retry_after=30)
        info = prepare_database_file(self.path)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise RequestDeferred('查询缓存须为当前用户的普通文件，权限为 600，且不得使用硬链接。',retry_after=30)
        connection = sqlite3.connect(str(self.path), timeout=25, isolation_level=None)
        return connection

    def run(self, account, session, operation, resource, fetch):
        # Only hashes go into keys. Responses can contain location/VIN; the
        # database is private plaintext, not a credential vault.
        account_key = digest(account)
        cache_key = digest(json.dumps([account, session, operation, resource]))
        self.cache_hit, self.fetched_at, self.next_query_at = False, None, None
        fetch_started = False
        try:
            with lock_context('query'), self._request_lock(), closing(self._connect()) as connection:
                connection.execute('BEGIN IMMEDIATE')
                try:
                    connection.execute('CREATE TABLE IF NOT EXISTS cooldown (key TEXT PRIMARY KEY, until REAL NOT NULL)')
                    connection.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, fetched REAL NOT NULL, expires REAL NOT NULL, data TEXT NOT NULL)')
                    connection.execute('CREATE TABLE IF NOT EXISTS status_attempts (key TEXT PRIMARY KEY, attempted REAL NOT NULL)')
                    interval = read_request_settings(self.path.parent)[1] if operation == 'status' else INTERVAL
                    now = self.clock()
                    connection.execute('DELETE FROM cache WHERE expires <= ?', (now,))
                    keys = ['gateway'] + (['status:' + account_key] if operation == 'status' else [])
                    deadlines = [connection.execute('SELECT until FROM cooldown WHERE key=?', (key,)).fetchone() for key in keys]
                    if operation == 'status':
                        attempt = connection.execute('SELECT attempted FROM status_attempts WHERE key=?', (account_key,)).fetchone()
                        if attempt:
                            deadlines[-1] = (attempt[0] + interval,)
                    self.next_query_at = max([now] + [row[0] for row in deadlines if row])
                    row = connection.execute('SELECT fetched,CASE WHEN length(CAST(data AS BLOB))<=? THEN data END '
                                             'FROM cache WHERE key=?',(MAX_CACHE_BYTES,cache_key)).fetchone()
                    unavailable_cache=False
                    if row and 0 <= now - row[0] < interval:
                        self.next_query_at = max(self.next_query_at, row[0] + interval)
                        try:result=_decode_cache(row[1])
                        except (ValueError,TypeError,RecursionError):
                            # Keep fetch timing, not a broken/oversized body. An
                            # empty payload is a non-reusable cache reservation.
                            unavailable_cache=True
                            if row[1]!='':connection.execute("UPDATE cache SET data='' WHERE key=?",(cache_key,))
                        else:
                            self.cache_hit, self.fetched_at = True, row[0]
                            connection.commit()
                            return result
                    # A 429 pauses every gateway and login operation in this
                    # local profile. Valid cached results remain readable.
                    if self.next_query_at > now:
                        wait = math.ceil(self.next_query_at - now)
                        if unavailable_cache:connection.commit()
                        reason='本地查询缓存暂不可用；' if unavailable_cache else '本机查询保护：'
                        raise RequestDeferred(reason+'请等待 %d 秒后再查询；未发送网络请求。' % wait, retry_after=wait)
                    if operation == 'status':
                        self.next_query_at = max(self.next_query_at, now + interval)
                        connection.execute('INSERT OR REPLACE INTO status_attempts VALUES (?, ?)', (account_key, now))
                        connection.execute('INSERT OR REPLACE INTO cooldown VALUES (?, ?)', ('status:' + account_key, now + interval))
                        # A killed process cannot roll back the already-started
                        # attempt and make the next caller immediately retry it.
                        connection.commit()
                        self._resume_status(connection,account_key,now,interval)
                    try:
                        fetch_started = True
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
                    if operation in ('status', 'vehicles', 'history', 'history_points'):
                        self.next_query_at = max(self.next_query_at, self.fetched_at + interval)
                        try:
                            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
                            if len(encoded.encode())>MAX_CACHE_BYTES:encoded=''
                        except (ValueError,TypeError,OverflowError,RecursionError):
                            # The outbound request already happened. Preserve its
                            # attempt interval even though this response is unusable.
                            connection.commit()
                            raise ApiError('网关响应包含无效数据，请稍后重试。',retryable=True) from None
                        # Retain up to 60 seconds so increasing the status interval
                        # can reuse the original response, with its original time.
                        connection.execute('INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?)',
                                           (cache_key, self.fetched_at, self.fetched_at + INTERVAL,
                                            encoded))
                    connection.commit()
                    return result
                finally:
                    if connection.in_transaction:
                        connection.rollback()
        except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError):
            if not fetch_started:
                raise RequestDeferred('查询缓存或并发锁不可用；未发送网络请求。',retry_after=30) from None
            raise ApiError('查询缓存或并发锁不可用；未绕过保护，请稍后重试。') from None
