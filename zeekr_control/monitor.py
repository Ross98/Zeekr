"""Persistent, conservative trip/charging transitions and notification outbox."""
import hashlib
import json

from .notifications import DeliveryError
from .summary import updated_at
from .vehicle_state import decode, numeric
from .tracks import TrackStore

MAX_AGE = 180000
STOP_WAIT = 600000


def summary(start, end, partial=False):
    distance = end['km'] - start['km'] if end['km'] is not None and start['km'] is not None else None
    if distance is not None and distance < 0:
        distance = None
        partial = True
    delta = end['soc'] - start['soc'] if end['soc'] is not None and start['soc'] is not None else None
    return {'start_time': start['time'], 'end_time': end['time'],
            'duration_seconds': (end['time'] - start['time']) / 1000,
            'distance_km': round(distance, 3) if distance is not None else None,
            'start_soc': start['soc'], 'end_soc': end['soc'],
            'soc_delta': round(delta, 3) if delta is not None else None, 'partial': partial}


def fmt(value, unit=''):
    return '未知' if value is None else ('%.2f' % value).rstrip('0').rstrip('.') + unit


def message_for(kind, data, event_id):
    title = {'trip_end': '本次行程已结束', 'charge_start': '检测到开始充电', 'charge_end': '充电已停止'}[kind]
    lines = [title]
    if kind == 'charge_start':
        lines += ['观测时间：' + updated_at(data['start_time']), '电量：' + fmt(data['start_soc'], '%')]
        if data['partial']:
            lines += ['实际开始时间未知；首次观测时已在充电。']
    else:
        lines += ['开始：' + updated_at(data['start_time']), '结束：' + updated_at(data['end_time']),
                  '观测时长：' + fmt(data['duration_seconds'] / 60, ' 分钟')]
        if kind == 'trip_end':
            lines += ['里程：' + fmt(data['distance_km'], ' km')]
        lines += ['电量：%s → %s' % (fmt(data['start_soc'], '%'), fmt(data['end_soc'], '%')),
                  '电量变化：' + fmt(data['soc_delta'], ' 个百分点'), 'kWh：暂无可靠数据']
        if data['partial']:
            lines += ['数据不完整：起点或期间观测存在缺口，仅汇总已观测部分。']
    lines += ['来源：车辆云端缓存，时间可能延迟。', '事件编号：' + event_id[:12]]
    return '\n'.join(lines)


class Monitor:
    def __init__(self, database_path, active_codes=(), stopped_codes=()):
        self.tracks = TrackStore(database_path)
        self.active_codes, self.stopped_codes = active_codes, stopped_codes
        with self.tracks.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS monitor_state (vehicle TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS monitor_events (
                id TEXT PRIMARY KEY, vehicle TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL,
                message TEXT NOT NULL, created INTEGER NOT NULL, delivery TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt INTEGER NOT NULL DEFAULT 0,
                error TEXT, sent_at INTEGER)''')
            db.execute('CREATE INDEX IF NOT EXISTS monitor_delivery ON monitor_events(delivery, next_attempt)')
            db.execute("UPDATE monitor_events SET delivery='uncertain', error='发送期间进程中断，需人工确认' WHERE delivery='sending'")

    def status(self, vehicle):
        with self.tracks.connect() as db:
            row = db.execute('SELECT payload FROM monitor_state WHERE vehicle=?', (vehicle,)).fetchone()
        return json.loads(row[0]) if row else {'last': None, 'trip': None, 'charge': None}

    def _event(self, db, vehicle, kind, data, now):
        identity = '%s:%s:%s' % (vehicle, kind, data['start_time'])
        event_id = hashlib.sha256(identity.encode()).hexdigest()
        db.execute('INSERT OR IGNORE INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                   (event_id, vehicle, kind, json.dumps(data), message_for(kind, data, event_id), now))

    def observe(self, vehicle, raw, now):
        point = decode(raw, self.active_codes, self.stopped_codes)
        state = self.status(vehicle)
        previous = state['last']
        timestamp = point['time']
        if timestamp is None or not -30000 <= now - timestamp <= MAX_AGE:
            return 'stale'
        if previous and timestamp <= previous['time']:
            return 'unchanged'
        point['observed'] = now
        continuous = previous is not None and timestamp - previous['time'] <= MAX_AGE and 0 <= now - previous['observed'] <= MAX_AGE
        moving = point['speed'] is not None and point['speed'] > 0
        distance_moved = continuous and previous['km'] is not None and point['km'] is not None and point['km'] > previous['km']
        trip = state['trip']
        if trip and not continuous:
            trip['partial'], trip['stop'] = True, None
        if trip is None and (moving or distance_moved):
            start = previous if continuous else point
            trip = {'start': start, 'stop': None, 'partial': not continuous, 'charging_time': None}
        if trip:
            # TrackStore deduplicates replays if state commit is interrupted.
            if trip['stop'] is None or moving:
                self.tracks.record(vehicle, raw, now, 180)
            if point['charging'] is True and trip.get('charging_time') is None:
                trip['charging_time'] = timestamp
            if moving or point['off'] is not True:
                trip['stop'] = None
            elif trip['stop'] is None:
                trip['stop'] = point
        charge = state['charge']
        if charge and not continuous:
            charge['partial'] = True
        with self.tracks.connect() as db:
            if trip and trip['stop'] and timestamp - trip['stop']['time'] >= STOP_WAIT and now - trip['stop']['observed'] >= STOP_WAIT:
                data = summary(trip['start'], trip['stop'], trip['partial'])
                if trip.get('charging_time') is not None and trip['charging_time'] <= trip['stop']['time']:
                    data['soc_delta'] = None
                    data['partial'] = True
                self._event(db, vehicle, 'trip_end', data, now)
                trip = None
            if point['charging'] is True and charge is None:
                charge = {'start': point, 'partial': not continuous or previous['charging'] is not False}
                self._event(db, vehicle, 'charge_start', summary(point, point, charge['partial']), now)
            elif point['charging'] is False and charge:
                self._event(db, vehicle, 'charge_end', summary(charge['start'], point, charge['partial']), now)
                charge = None
            state.update(last=point, trip=trip, charge=charge)
            db.execute('INSERT OR REPLACE INTO monitor_state VALUES (?,?)', (vehicle, json.dumps(state)))
        return 'fresh'

    def events(self, limit=100):
        with self.tracks.connect() as db:
            rows = db.execute('SELECT id,kind,summary,message,delivery,attempts,error FROM monitor_events ORDER BY created, rowid LIMIT ?', (limit,)).fetchall()
        return [dict(id=r[0], kind=r[1], summary=json.loads(r[2]), message=r[3], delivery=r[4], attempts=r[5], error=r[6]) for r in rows]

    def deliver(self, sender, now):
        # One worker owns the process lock; compare-and-set also guards claims.
        with self.tracks.connect() as db:
            rows = db.execute("SELECT id,message,attempts FROM monitor_events WHERE delivery='pending' AND next_attempt<=? ORDER BY created,rowid LIMIT 10", (now,)).fetchall()
        for event_id, message, attempts in rows:
            with self.tracks.connect() as db:
                claimed = db.execute("UPDATE monitor_events SET delivery='sending', attempts=attempts+1 WHERE id=? AND delivery='pending'", (event_id,)).rowcount
            if not claimed:
                continue
            error, next_attempt, sent_at = None, 0, None
            try:
                sender(message)
                delivery, sent_at = 'sent', now
            except DeliveryError as exc:
                delivery = 'uncertain' if exc.ambiguous else 'failed' if exc.permanent or attempts >= 5 else 'pending'
                error = str(exc)[:100]
                next_attempt = now + min(3600, 60 * 2 ** attempts) * 1000
            except Exception:
                delivery, error = 'uncertain', '发送结果未确认'
            with self.tracks.connect() as db:
                db.execute('UPDATE monitor_events SET delivery=?,error=?,next_attempt=?,sent_at=? WHERE id=?',
                           (delivery, error, next_attempt, sent_at, event_id))
