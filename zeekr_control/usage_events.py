"""Bounded event reads and scalar-only projections shared by personal tools."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import sqlite3

from .archive_reader import _private
from .trip_visibility import has_charge_trash, visible_clause
from .start_evidence import from_summary as start_evidence

MAX_SUMMARY_BYTES = 2 * 1024 * 1024
MAX_SCAN = 250000
MAX_EVENTS = 10000
VALID_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')


def number(value, low=0, high=1e12):
    return value if type(value) in (int, float) and math.isfinite(value) and low <= value <= high else None


def total(values):
    values = [value for value in values if value is not None]
    return round(sum(values), 6) if values else None


def _object(value):
    return value if isinstance(value, dict) else {}


def project(identity, kind, summary):
    if kind not in ('trip_end', 'charge_end') or not isinstance(summary, dict):
        return None
    if not isinstance(identity, str) or not VALID_ID.fullmatch(identity):
        return None
    start, end = (number(summary.get(key), 1, 32503680000000) for key in ('start_time', 'end_time'))
    if end is None:
        return None
    report = _object(summary.get('report_v2'))
    metrics, quality = _object(report.get('metrics')), _object(report.get('quality'))
    reasons = quality.get('quality_reasons')
    reasons = reasons if isinstance(reasons, list) else []
    overlap = metrics.get('charge_overlap') is True or 'charge_overlap' in reasons
    complete = (summary.get('partial') is False and report.get('partial') is not True
                and start is not None and end > start and not overlap)
    duration = number(summary.get('duration_seconds'), 0, 366*86400)
    if start is None or end < start or duration is None or abs(duration-(end-start)/1000) > 1:
        duration = None
    distance = number(summary.get('distance_km'), 0, 1e7)
    a, b = (number(summary.get(key), 0, 100) for key in ('start_soc', 'end_soc'))
    delta = number(summary.get('soc_delta'), -100, 100)
    if a is None or b is None or delta is None or abs(b-a-delta) > .001:
        delta = None
    source = _object(report.get('profile_snapshot')) if 'profile_snapshot' in report else summary
    capacity = number(source.get('battery_capacity_kwh'), .001, 1000)
    estimated = None
    # Completeness describes the whole event, not the validity of its observed endpoints.
    energy_delta = (delta if start is not None and end > start and not overlap
                    and not quality.get('decoder_changed_mid_session') else None)
    if energy_delta is not None and capacity is not None:
        change = -energy_delta if kind == 'trip_end' else energy_delta
        if change >= 0:
            estimated = round(change*capacity/100, 6)
    mode = _object(report.get('start')).get('charging_mode')
    return {'id': identity, 'kind': kind, 'start_time': start, 'end_time': end,
            'start_evidence': start_evidence(summary, kind),
            'duration_seconds': duration, 'distance_km': distance, 'start_soc': a, 'end_soc': b,
            'soc_delta': delta, 'energy_soc_delta': energy_delta,
            'partial': not complete, 'battery_capacity_kwh': capacity,
            'estimated_kwh': estimated, 'charge_mode': mode if mode in ('ac', 'dc') else None,
            'energy_source': 'soc_capacity_estimate' if estimated is not None else None}


class UsageEvents:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        if not self.path.exists() and not self.path.is_symlink():
            yield None
            return
        _private(self.path.parent, directory=True)
        _private(self.path)
        db = sqlite3.connect(self.path.absolute().as_uri()+'?mode=ro', uri=True, timeout=5)
        try:
            db.execute('PRAGMA query_only=ON')
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_events'").fetchone()
            yield db if exists else None
        finally:
            db.close()

    @staticmethod
    def _decode(identity, kind, encoded, size):
        if not isinstance(encoded, str) or size > MAX_SUMMARY_BYTES:
            return None
        try:
            return project(identity, kind, json.loads(encoded))
        except (ValueError, TypeError, RecursionError):
            return None

    def between(self, vehicle, lower, upper, *, overlap=False):
        if not isinstance(vehicle, str) or not vehicle or not 0 <= lower < upper:
            raise ValueError('车辆或事件范围无效。')
        events, invalid, scanned, cursor = [], 0, 0, 0
        with self.connect() as db:
            if db is None:
                return {'events': [], 'unreadable_or_undated': 0}
            high = db.execute('SELECT MAX(rowid) FROM monitor_events WHERE vehicle=?', (vehicle,)).fetchone()[0] or 0
            while cursor < high:
                # Short bounded reads release SQLite's cursor lock before JSON parsing.
                rows = db.execute('SELECT rowid,id,kind,CASE WHEN length(CAST(summary AS BLOB))<=? THEN summary END,length(CAST(summary AS BLOB)) '
                                  'FROM monitor_events WHERE vehicle=? AND rowid>? AND rowid<=? '
                                  "AND kind IN ('trip_end','charge_end') AND "+visible_clause(db)+' ORDER BY rowid LIMIT 32',
                                  (MAX_SUMMARY_BYTES, vehicle, cursor, high)).fetchall()
                if not rows:
                    break
                for rowid, identity, kind, encoded, size in rows:
                    scanned += 1
                    if scanned > MAX_SCAN:
                        raise ValueError('事件历史过大，需先建立归期索引。')
                    event = self._decode(identity, kind, encoded, size)
                    if event is None:
                        invalid += 1
                    else:
                        start,end=event['start_time'],event['end_time']
                        matches=(start<upper and end>lower) if overlap and start is not None and start<end else lower<=end<upper
                        if matches:
                            events.append(event)
                            if len(events) > MAX_EVENTS:
                                raise ValueError('周期内事件过多，请缩小范围。')
                    cursor = rowid
        events.sort(key=lambda row: (row['end_time'], row['id']), reverse=True)
        return {'events': events, 'unreadable_or_undated': invalid}

    def get(self, vehicle, identity):
        if not isinstance(identity, str) or not VALID_ID.fullmatch(identity) or not isinstance(vehicle, str) or not vehicle:
            raise ValueError('请选择当前车辆的有效事件。')
        with self.connect() as db:
            row = db.execute('SELECT kind,CASE WHEN length(CAST(summary AS BLOB))<=? THEN summary END,length(CAST(summary AS BLOB)) '
                             'FROM monitor_events WHERE vehicle=? AND id=? AND '+visible_clause(db),
                             (MAX_SUMMARY_BYTES, vehicle, identity)).fetchone() if db else None
        result = self._decode(identity, *row) if row else None
        if result is None:
            raise ValueError('事件不存在、格式无效或不属于当前车辆。')
        return result

    def hidden_charge_ids(self, vehicle, identities):
        identities = {identity for identity in identities if isinstance(identity, str) and VALID_ID.fullmatch(identity)}
        if not isinstance(vehicle, str) or not vehicle:
            raise ValueError('车辆无效。')
        if not identities:
            return set()
        hidden = set()
        with self.connect() as db:
            if db is None or not has_charge_trash(db):
                return hidden
            ordered = sorted(identities)
            for offset in range(0, len(ordered), 500):
                batch = ordered[offset:offset+500]
                marks = ','.join('?' for _ in batch)
                rows = db.execute(f'SELECT event_id FROM charge_record_trash WHERE vehicle=? AND event_id IN ({marks})',
                                  (vehicle, *batch)).fetchall()
                hidden.update(row[0] for row in rows)
        return hidden
