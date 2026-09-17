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


class TrackStore:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError('轨迹路径不可使用符号链接。')
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
        connection = sqlite3.connect(str(self.path), timeout=10)
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
        start = datetime.strptime(date, '%Y-%m-%d').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        if start.strftime('%Y-%m-%d') != date:
            raise ValueError('日期格式应为 YYYY-MM-DD。')
        lower, upper = int(start.timestamp() * 1000), int((start + timedelta(days=1)).timestamp() * 1000)
        with self.connect() as connection:
            rows = connection.execute('SELECT state_time, observed_time, gap_seconds, location FROM observations '
                'WHERE vehicle=? AND COALESCE(state_time, observed_time)>=? AND COALESCE(state_time, observed_time)<? '
                'ORDER BY observed_time, id LIMIT 5001', (vehicle, lower, upper)).fetchall()
        observations, segments, current = [], [], []
        previous = None
        for timestamp, observed, gap, encoded in rows[:5000]:
            location = json.loads(encoded)
            point = dict(location, state_time=timestamp, observed_time=observed,
                         time_label=updated_at(timestamp if timestamp is not None else observed),
                         time_source='缓存状态时间' if timestamp is not None else '本机观测时间', gap_seconds=gap)
            observations.append(point)
            usable = location['trusted'] and location['plottable'] and timestamp is not None
            continuous = previous is not None and 0 < timestamp - previous['state_time'] <= gap * 1000 if usable else False
            if usable and previous is not None:
                continuous = continuous and 0 <= observed - previous['observed_time'] <= gap * 1000
            if not usable or not continuous:
                if current:
                    segments.append(current)
                current = []
            if usable:
                current.append(point)
                previous = point
            else:
                previous = None
        if current:
            segments.append(current)
        return {'observations': observations, 'segments': segments, 'truncated': len(rows) > 5000,
                'source': '本地采样', 'date': date, 'count': len(observations)}
