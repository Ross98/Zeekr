"""Private observations, cache deduplication and conservative route segmentation."""
from datetime import datetime, timedelta
from contextlib import contextmanager
from zoneinfo import ZoneInfo
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .web_model import parse_location
from .summary import number, updated_at


MAX_GAP_SECONDS = 180
MAX_POINTS = 5000


def day_bounds(date):
    start = datetime.strptime(date, '%Y-%m-%d').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    if start.strftime('%Y-%m-%d') != date:
        raise ValueError('日期格式应为 YYYY-MM-DD。')
    return int(start.timestamp() * 1000), int((start + timedelta(days=1)).timestamp() * 1000)


def valid_timestamp(value):
    return type(value) in (int, float) and 0 < value <= 32503680000000


def empty_route(date):
    return {'observations': [], 'segments': [], 'gaps': [], 'count': 0, 'date': date,
            'source': '本地采样', 'truncated': False,
            'quality': {'trusted_count': 0, 'untrusted_count': 0, 'unplottable_count': 0,
                        'gap_count': 0, 'segment_count': 0}}


def _gap(start, end, reason, unknown=False):
    duration = ((end - start) / 1000 if not unknown and valid_timestamp(start)
                and valid_timestamp(end) and end >= start else None)
    return {'start_time': start, 'end_time': end, 'duration_seconds': duration, 'reason': reason}


class TrackStore:
    def __init__(self, path, readonly=False):
        self.path = Path(path)
        self.readonly = readonly
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError('轨迹路径不可使用符号链接。')
        if readonly:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent.stat().st_mode & 0o077 or self.path.parent.stat().st_uid != os.getuid():
            raise ValueError('轨迹目录必须为当前用户所有且权限为 700。')
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_uid != os.getuid() or os.fstat(fd).st_mode & 0o077:
                raise ValueError('轨迹文件必须为当前用户所有且权限为 600。')
        finally:
            os.close(fd)
        with self.connect() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY, vehicle TEXT NOT NULL, cache_key TEXT NOT NULL,
                state_time INTEGER, observed_time INTEGER NOT NULL, gap_seconds INTEGER NOT NULL,
                location TEXT NOT NULL, UNIQUE(vehicle, cache_key))''')
            connection.execute('CREATE INDEX IF NOT EXISTS vehicle_time ON observations(vehicle, observed_time)')

    @contextmanager
    def connect(self):
        connection = (sqlite3.connect(self.path.absolute().as_uri() + '?mode=ro', uri=True, timeout=10)
                      if self.readonly else sqlite3.connect(str(self.path), timeout=10))
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record(self, vehicle, data, observed_time, gap_seconds):
        location = parse_location(data)
        timestamp = number(data.get('updateTime'), 1, 32503680000000)
        timestamp = int(timestamp) if timestamp is not None else None
        identity = [timestamp, location]
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with self.connect() as connection:
            cursor = connection.execute('INSERT OR IGNORE INTO observations '
                '(vehicle, cache_key, state_time, observed_time, gap_seconds, location) VALUES (?, ?, ?, ?, ?, ?)',
                (vehicle, digest, timestamp, observed_time, gap_seconds, json.dumps(location, ensure_ascii=False)))
            return cursor.rowcount == 1

    def vehicles(self):
        with self.connect() as connection:
            rows = connection.execute('SELECT vehicle FROM observations GROUP BY vehicle ORDER BY MIN(id)').fetchall()
        return [{'key': row[0], 'label': '本地车辆 %d' % index} for index, row in enumerate(rows, 1)]

    def day(self, vehicle, date):
        lower, upper = day_bounds(date)
        return self._range(vehicle, date, lower, upper)

    def between(self, vehicle, start, end, date):
        """Include the actual trip endpoints, even when the trip crosses midnight."""
        day_bounds(date)
        if not valid_timestamp(start) or not valid_timestamp(end) or end < start:
            raise ValueError('行程时间范围无效。')
        return self._range(vehicle, date, start, end, inclusive=True)

    def _range(self, vehicle, date, lower, upper, inclusive=False):
        result = empty_route(date)
        if not vehicle or not self.path.exists():
            return result
        with self.connect() as connection:
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='observations'").fetchone():
                return result
            rows = connection.execute('SELECT state_time, observed_time, gap_seconds, location FROM observations '
                'WHERE vehicle=? AND COALESCE(state_time, observed_time)>=? AND COALESCE(state_time, observed_time)'
                + ('<=?' if inclusive else '<?') + ' ORDER BY observed_time, id LIMIT ?',
                (vehicle, lower, upper, MAX_POINTS + 1)).fetchall()
        observations, segments, gaps, current = [], [], [], []
        previous = None
        pending_gap = None
        unknown_gap_time = False
        for timestamp, observed, gap, encoded in rows[:MAX_POINTS]:
            location = json.loads(encoded)
            point = dict(location, state_time=timestamp, observed_time=observed,
                         time_label=updated_at(timestamp if timestamp is not None else observed),
                         time_source='缓存状态时间' if timestamp is not None else '本机观测时间', gap_seconds=gap)
            observations.append(point)
            reasons = []
            if not valid_timestamp(timestamp):
                reasons.append('缓存状态时间缺失，无法确认路线连续')
            if location.get('trusted') is not True:
                reasons.append('位置不可信，未连线')
            if location.get('plottable') is not True:
                reasons.append('位置无法绘制，未连线')
            if reasons:
                if current:
                    segments.append(current)
                current = []
                unknown_gap_time = unknown_gap_time or not valid_timestamp(timestamp)
                reason = '；'.join(reasons)
                if pending_gap is None:
                    pending_gap = _gap(previous['state_time'] if previous else timestamp,
                                       timestamp, reason, unknown_gap_time)
                else:
                    pending_gap['end_time'] = timestamp
                    if reason not in pending_gap['reason']:
                        pending_gap['reason'] += '；' + reason
                previous = None
                continue
            if pending_gap is not None:
                gaps.append(_gap(pending_gap['start_time'], timestamp, pending_gap['reason'], unknown_gap_time))
                pending_gap, unknown_gap_time = None, False
            elif previous is not None:
                threshold = min(MAX_GAP_SECONDS, max(0, gap)) * 1000
                state_delta = timestamp - previous['state_time']
                observed_delta = observed - previous['observed_time']
                reason = ('缓存状态时间未递增，未连线' if state_delta <= 0 else
                          '缓存状态时间间隔超过采样连续性上限' if state_delta > threshold else
                          '本机观测时间倒退，未连线' if observed_delta < 0 else
                          '本机观测间隔超过采样连续性上限' if observed_delta > threshold else None)
                if reason:
                    if current:
                        segments.append(current)
                    current = []
                    gaps.append(_gap(previous['state_time'], timestamp, reason, observed_delta < 0))
            current.append(point)
            previous = point
        if current:
            segments.append(current)
        if pending_gap is not None:
            gaps.append(_gap(pending_gap['start_time'], pending_gap['end_time'],
                             pending_gap['reason'], unknown_gap_time))
        truncated = len(rows) > MAX_POINTS
        # A day need not contain driving at midnight. Boundary evidence applies
        # only to a known trip interval, and never to a capped output tail.
        if inclusive and observations:
            known_times = [point['state_time'] for point in observations if valid_timestamp(point['state_time'])]
            # Replayed/unknown times cannot establish missing boundary coverage.
            first = min(known_times) if len(known_times) == len(observations) else None
            last = max(known_times) if len(known_times) == len(observations) else None
            if first is not None and first - lower > MAX_GAP_SECONDS * 1000:
                gaps.insert(0, _gap(lower, first, '行程记录开始后首个位置采样较晚'))
            if not truncated and last is not None and upper - last > MAX_GAP_SECONDS * 1000:
                gaps.append(_gap(last, upper, '末个位置采样早于行程末次观测'))
        trusted = sum(point.get('trusted') is True for point in observations)
        result.update(observations=observations, segments=segments, gaps=gaps,
                      truncated=truncated, count=len(observations),
                      quality={'trusted_count': trusted, 'untrusted_count': len(observations) - trusted,
                               'unplottable_count': sum(point.get('plottable') is not True for point in observations),
                               'gap_count': len(gaps), 'segment_count': len(segments)})
        return result
