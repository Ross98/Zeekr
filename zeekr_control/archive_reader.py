"""Bounded, read-only access to private snapshots with explicit public projection."""
from contextlib import contextmanager
from datetime import datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from .snapshot_archive import BEIJING
from .tracks import day_bounds
from .vehicle_parameters import lookup, parameters
from .web_model import build_model


MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
READ_COLUMNS = 'id,state_time,fetched_at,observed_at,source,digest'
STALE_MS = 10 * 60 * 1000


def _private(path, directory=False):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
            or not directory and info.st_nlink != 1):
        raise OSError('归档路径或权限不安全。')


def _month(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{6}', value):
        raise ValueError('归档月份无效。')
    datetime.strptime(value, '%Y%m')
    return value


def _selection(key):
    if not isinstance(key, str) or not re.fullmatch(r'[0-9]{6}\.[1-9][0-9]{0,18}', key):
        raise ValueError('归档记录无效。')
    month, row = key.split('.')
    if int(row) > 2 ** 63 - 1:
        raise ValueError('归档记录编号无效。')
    return _month(month), int(row)


def _context(scope, vehicle):
    if not all(isinstance(value, str) and 0 < len(value) <= 256 for value in (scope, vehicle)):
        raise ValueError('请先选择当前账号的车辆。')


def metadata(month, row, previous=None):
    state = row['state_time']
    valid = type(state) is int and 0 < state <= 9999999999999
    flags, gap = [], None
    if not valid:
        flags.append('unknown_time')
    elif state > row['fetched_at'] + 60000:
        flags.append('future_time')
    elif max(row['fetched_at'], row['observed_at']) - state > STALE_MS:
        flags.append('stale')
    change = 'first'
    if previous:
        old = previous['state_time']
        if state == old:
            change = 'repeat' if row['digest'] == previous['digest'] else 'revision'
        elif valid and type(old) is int and state < old:
            change = 'regression'
        else:
            change = 'new' if valid else 'unknown'
        if row['observed_at'] - previous['observed_at'] > STALE_MS:
            gap = (row['observed_at'] - previous['observed_at']) / 1000
    return {'key': '%s.%d' % (month, row['id']), 'state_time': state if valid else None,
            'fetched_at': row['fetched_at'], 'observed_at': row['observed_at'],
            'source': row['source'] if row['source'] in ('monitor', 'manual') else 'unknown',
            'change': change, 'flags': flags, 'gap_seconds': gap,
            'delay_seconds': (row['fetched_at'] - state) / 1000 if valid else None}


class ArchiveReader:
    def __init__(self, root):
        self.root = Path(root)

    @contextmanager
    def connect(self, month):
        month = _month(month)
        year = self.root / month[:4]
        path = year / (month[4:] + '.sqlite3')
        # Check each component before exists(): dangling symlinks must not look empty.
        for directory in (self.root.parent, self.root, year):
            if not directory.exists() and not directory.is_symlink():
                yield None
                return
            _private(directory, directory=True)
        if not path.exists() and not path.is_symlink():
            yield None
            return
        _private(path)
        db = sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            if db.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise ValueError('不支持的归档版本。')
            yield db
        finally:
            db.close()

    def _months(self):
        if not self.root.exists() and not self.root.is_symlink():
            return []
        _private(self.root.parent, directory=True)
        _private(self.root, directory=True)
        months = []
        for year in self.root.iterdir():
            if not re.fullmatch(r'[0-9]{4}', year.name):
                continue
            _private(year, directory=True)
            for path in year.iterdir():
                if re.fullmatch(r'(0[1-9]|1[0-2])\.sqlite3', path.name):
                    months.append(year.name + path.stem)
        return sorted(months)

    def time_bounds(self, scope, vehicle):
        """Read scoped observation limits without loading snapshot payloads."""
        _context(scope, vehicle)
        first, last = None, None
        for month in self._months():
            with self.connect(month) as db:
                if db is None:
                    continue
                args = (scope, vehicle)
                a = db.execute('SELECT observed_at FROM reads WHERE scope_key=? AND vehicle_key=? '
                               'ORDER BY observed_at,id LIMIT 1', args).fetchone()
                b = db.execute('SELECT observed_at FROM reads WHERE scope_key=? AND vehicle_key=? '
                               'ORDER BY observed_at DESC,id DESC LIMIT 1', args).fetchone()
                if a:
                    first = a[0] if first is None else min(first, a[0])
                    last = b[0] if last is None else max(last, b[0])
        return (first, last) if first is not None else None

    def _previous(self, month, scope, vehicle, observed, row_id=0, db=None):
        query = ('SELECT ' + READ_COLUMNS + ' FROM reads WHERE scope_key=? AND vehicle_key=? '
                 'AND (observed_at<? OR (observed_at=? AND id<?)) ORDER BY observed_at DESC,id DESC LIMIT 1')
        args = (scope, vehicle, observed, observed, row_id)
        if db is not None:
            row = db.execute(query, args).fetchone()
            if row:
                return row
        for earlier in reversed([value for value in self._months() if value < month]):
            with self.connect(earlier) as connection:
                if connection:
                    row = connection.execute(query, args).fetchone()
                    if row:
                        return row
        return None

    def timeline(self, scope, vehicle, date, cursor=None, limit=120):
        _context(scope, vehicle)
        lower, upper = day_bounds(date)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('归档分页大小无效。')
        month = datetime.fromtimestamp(lower / 1000, BEIJING).strftime('%Y%m')
        after_time, after_id = lower, 0
        if cursor is not None:
            if not isinstance(cursor, str) or not re.fullmatch(r'[0-9]{1,13}:[1-9][0-9]{0,18}', cursor):
                raise ValueError('归档游标无效。')
            after_time, after_id = map(int, cursor.split(':'))
            if not lower <= after_time < upper or after_id > 2 ** 63 - 1:
                raise ValueError('归档游标不属于所选日期。')
        result = {'date': date, 'items': [], 'next_cursor': None,
                  'time_basis': '北京时间采集日期', 'gap_threshold_seconds': STALE_MS // 1000}
        with self.connect(month) as db:
            if db is None:
                if cursor:
                    raise ValueError('归档游标已失效。')
                return result
            if cursor and not db.execute('SELECT 1 FROM reads WHERE scope_key=? AND vehicle_key=? AND id=? AND observed_at=?',
                                         (scope, vehicle, after_id, after_time)).fetchone():
                raise ValueError('归档游标已失效。')
            rows = db.execute('SELECT ' + READ_COLUMNS + ' FROM reads WHERE scope_key=? AND vehicle_key=? '
                              'AND observed_at>=? AND observed_at<? AND (observed_at>? OR (observed_at=? AND id>?)) '
                              'ORDER BY observed_at,id LIMIT ?',
                              (scope, vehicle, lower, upper, after_time, after_time, after_id, limit + 1)).fetchall()
            previous = self._previous(month, scope, vehicle, after_time, after_id + 1 if cursor else 0, db)
            for row in rows[:limit]:
                result['items'].append(metadata(month, row, previous))
                previous = row
            if len(rows) > limit:
                last = rows[limit - 1]
                result['next_cursor'] = '%d:%d' % (last['observed_at'], last['id'])
        return result

    def read(self, scope, vehicle, key):
        """Private server-side raw access; public callers must use snapshot()."""
        _context(scope, vehicle)
        month, row_id = _selection(key)
        with self.connect(month) as db:
            row = db.execute('SELECT reads.*,encoding,raw_bytes,substr(compressed_json,1,?) AS compressed_json FROM reads '
                             'JOIN payloads USING(digest) WHERE scope_key=? AND vehicle_key=? AND id=?',
                             (MAX_PAYLOAD_BYTES + 65537, scope, vehicle, row_id)).fetchone() if db is not None else None
            if row is None:
                raise ValueError('归档记录不存在或不属于当前车辆。')
            raw = self._payload(row)
            previous = self._previous(month, scope, vehicle, row['observed_at'], row_id, db)
            return metadata(month, row, previous), raw

    @staticmethod
    def _payload(row):
        if (row['encoding'] != 'gzip-json-v1' or not 0 < row['raw_bytes'] <= MAX_PAYLOAD_BYTES
                or len(row['compressed_json']) > MAX_PAYLOAD_BYTES + 65536):
            raise ValueError('归档正文格式或大小无效。')
        with gzip.GzipFile(fileobj=io.BytesIO(row['compressed_json'])) as compressed:
            payload = compressed.read(MAX_PAYLOAD_BYTES + 1)
        if (len(payload) != row['raw_bytes'] or len(payload) > MAX_PAYLOAD_BYTES or
                hashlib.sha256(payload).hexdigest() != row['digest']):
            raise ValueError('归档正文校验失败。')
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise ValueError('归档正文不是车辆快照。')
        return raw

    def _iter_rows(self, scope, vehicle, lower, upper, limit):
        """Private metadata batches, with each query cursor exhausted before yielding."""
        _context(scope, vehicle)
        if (type(lower) is not int or type(upper) is not int or lower < 0 or
                not 0 < upper-lower <= 33*86400000 or type(limit) is not int or not 1 <= limit <= 50000):
            raise ValueError('归档分析范围无效。')
        start_month = datetime.fromtimestamp(lower/1000, BEIJING).strftime('%Y%m')
        end_month = datetime.fromtimestamp((upper-1)/1000, BEIJING).strftime('%Y%m')
        previous, count = None, 0
        for month in self._months():
            if not start_month <= month <= end_month:
                continue
            with self.connect(month) as db:
                if db is None:
                    continue
                if previous is None:
                    previous = self._previous(month, scope, vehicle, lower, 0, db)
                # Materialize bounded metadata only, releasing the range cursor's
                # SQLite read lock before decoding. Each payload lookup is short;
                # long analytics must not hold up the monitor's archive commits.
                rows = db.execute('SELECT ' + READ_COLUMNS + ' FROM reads WHERE scope_key=? AND vehicle_key=? '
                                  'AND observed_at>=? AND observed_at<? ORDER BY observed_at,id LIMIT ?',
                                  (scope, vehicle, lower, upper, limit-count+1)).fetchall()
                for row in rows:
                    count += 1
                    if count > limit:
                        raise ValueError('归档观测超过 50000 条，请缩小日期范围。')
                    yield db, row, metadata(month, row, previous)
                    previous = row

    def iter_metadata(self, scope, vehicle, lower, upper, limit=50000):
        for _, _, record in self._iter_rows(scope, vehicle, lower, upper, limit):
            yield record

    def iter_records(self, scope, vehicle, lower, upper, limit=50000):
        """Server-only streaming analytics input; fail rather than silently truncate."""
        last_digest, last_raw = None, None
        for db, row, record in self._iter_rows(scope, vehicle, lower, upper, limit):
            if row['digest'] != last_digest:
                payload = db.execute('SELECT digest,encoding,raw_bytes,substr(compressed_json,1,?) AS compressed_json '
                                     'FROM payloads WHERE digest=?',
                                     (MAX_PAYLOAD_BYTES+65537, row['digest'])).fetchone()
                if payload is None:
                    raise ValueError('归档正文缺失。')
                last_raw, last_digest = self._payload(payload), row['digest']
            yield record, last_raw

    def snapshot(self, scope, vehicle, key):
        record, raw = self.read(scope, vehicle, key)
        return self._project(record, raw)

    @staticmethod
    def _project(record, raw):
        model = build_model(raw)
        projection = parameters(raw, model)
        for field in projection['fields']:
            if field['path'] == 'updateTime' and record['state_time'] is not None:
                projection['counts'][field['status']] -= 1
                projection['counts']['known'] += 1
                field.update(status='known', evidence='车辆快照时间',
                    value=datetime.fromtimestamp(record['state_time']/1000, BEIJING).strftime('%Y-%m-%d %H:%M:%S') + '（北京时间）')
        return {'record': record, 'summary': dict(model['metrics'], lock=model['lock']['value'],
                charging=model['charging']['value'], doors=model['closure']['doors'],
                windows=model['closure']['windows']), 'fields': projection['fields'],
                'counts': projection['counts'], 'groups': projection['groups']}

    def compare(self, scope, vehicle, before, after):
        left_record, left_raw = self.read(scope, vehicle, before)
        right_record, right_raw = self.read(scope, vehicle, after)
        left, right = self._project(left_record, left_raw), self._project(right_record, right_raw)
        changes = []
        for a, b in zip(left['fields'], right['fields']):
            old, new = lookup(left_raw, a['path']), lookup(right_raw, b['path'])
            if (type(old), old, a['status']) != (type(new), new, b['status']):
                changes.append({'path': a['path'], 'name': a['name'], 'group': a['group'],
                                'unit': a['unit'], 'before': a, 'after': b,
                                'display_limited': a['raw'] == b['raw']})
        return {'before': left['record'], 'after': right['record'], 'changes': changes,
                'compared_fields': len(left['fields'])}
