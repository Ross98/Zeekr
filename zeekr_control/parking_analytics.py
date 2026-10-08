"""Parking SOC observations, never joined across charging or uncertain gaps."""
from datetime import datetime

from .snapshot_archive import BEIJING
from .tracks import day_bounds
from .vehicle_state import decode, numeric
from .parking_events import build_events, time_advances
from .usage_events import UsageEvents
from .web_model import parse_location


MAX_GAP_MS = 600000
REASONS = {
    'start_unobserved': '未观测到停车开始边界', 'end_unobserved': '未观测到停车结束边界',
    'charging_boundary': '区间邻接充电，单独列为片段', 'unknown_state': '动力、速度或充电状态证据不足',
    'invalid_time': '存在旧缓存、异常时间或时间倒退', 'gap': '有效车辆观测间隔超过 10 分钟',
    'movement_conflict': '停车观测间里程发生变化', 'soc_increase': '区间出现电量回升',
    'soc_missing': '区间存在无效或缺失电量', 'insufficient_samples': '有效停车样本不足',
    'range_boundary': '停车区间触及查询边界',
}


def analyze_parking(samples, lower, upper, capacity=None):
    capacity = numeric(capacity, 0.001, 1000)
    quality = {'read_count': 0, 'boundary_reads': 0, 'repeat_reads': 0, 'revisions': 0, 'excluded_reads': 0}
    sessions, active, previous = [], None, None
    prior_kind, prior_reason = None, 'start_unobserved'

    def revised():
        pending = None
        for sample in samples:
            record = sample['record']
            in_range = lower <= record['observed_at'] < upper
            quality['read_count' if in_range else 'boundary_reads'] += 1
            if (record['change'] == 'repeat' and not record['flags']
                    and not time_advances(record, pending['record'] if pending else None)):
                quality['repeat_reads'] += int(in_range)
                continue
            if (record['change'] == 'revision' and not record['flags'] and pending
                    and record['state_time'] == pending['record']['state_time']):
                quality['revisions'] += int(in_range)
                pending = sample
                continue
            if pending is not None:
                yield pending
            pending = sample
        if pending is not None:
            yield pending

    def close(reason=None):
        nonlocal active
        if active is None:
            return
        first, last = active['first'], active['last']
        start, end = first['record']['state_time'], last['record']['state_time']
        reasons = active['reasons']
        if reason:
            reasons.add(reason)
        if start < lower or end >= upper:
            reasons.add('range_boundary')
        if active['count'] < 2 or end <= start:
            reasons.add('insufficient_samples')
        start_soc, end_soc = first['state']['soc'], last['state']['soc']
        drop = round(start_soc - end_soc, 6) if start_soc is not None and end_soc is not None else None
        duration = max(0, end - start) / 1000
        eligible = not reasons and drop is not None and drop >= 0
        if end >= lower and start < upper:
            category = ('multi_day' if duration >= 86400 else 'overnight' if
                        datetime.fromtimestamp(start/1000, BEIJING).date() !=
                        datetime.fromtimestamp(end/1000, BEIJING).date() else 'same_day')
            sessions.append({'id': first['record']['key'], 'start': first['record'], 'end': last['record'],
                'start_time': start, 'end_time': end, 'duration_seconds': duration,
                'sample_count': active['count'], 'start_soc': start_soc, 'end_soc': end_soc,
                'soc_drop': drop, 'start_km': first['state']['km'], 'end_km': last['state']['km'],
                'start_inside_temp': first.get('inside_temp'), 'end_inside_temp': last.get('inside_temp'),
                'start_inside_time': first.get('inside_time'), 'end_inside_time': last.get('inside_time'),
                'eligible': eligible, 'reasons': sorted(reasons), 'reason_labels': [REASONS[r] for r in sorted(reasons)],
                'estimated_kwh': round(drop*capacity/100, 4) if eligible and capacity else None,
                'capacity_kwh': capacity, 'max_gap_seconds': active['max_gap']/1000,
                'soc_drop_per_24h': round(drop*86400/duration, 4) if eligible and duration >= 3600 else None,
                'category': category})
        active = None

    for sample in revised():
        record, state = sample['record'], sample['state']
        stamp = record['state_time']
        invalid = (record['flags'] or record['change'] == 'regression' or stamp is None)
        gap = bool(previous and stamp is not None and previous['record']['state_time'] is not None
                   and (stamp - previous['record']['state_time'] > MAX_GAP_MS
                        or record['observed_at'] - previous['record']['observed_at'] > MAX_GAP_MS))
        if invalid:
            kind, reason = 'unknown', 'invalid_time'
        elif state['charging'] is True:
            kind, reason = 'charging', 'charging_boundary'
        elif state['charging'] is None:
            kind, reason = 'unknown', 'unknown_state'
        elif state['off'] is True and state['speed'] is not None and state['speed'] > 0:
            kind, reason = 'unknown', 'movement_conflict'
        elif state['off'] is False or state['speed'] is not None and state['speed'] > 0:
            kind, reason = 'moving', None
        elif state['off'] is True:
            old = previous['state'] if previous else {}
            stationary_odometer = state['km'] is not None and old.get('km') == state['km']
            moved = (old.get('off') is True and old.get('km') is not None and state['km'] is not None
                     and old['km'] != state['km'])
            if moved:
                kind, reason = 'unknown', 'movement_conflict'
            elif state['speed'] == 0 or stationary_odometer:
                kind, reason = 'parked', None
            else:
                kind, reason = 'unknown', 'unknown_state'
        else:
            kind, reason = 'unknown', 'unknown_state'

        if gap:
            close('gap')
            prior_kind, prior_reason = 'unknown', 'gap'
        if kind != 'parked':
            close(reason)
            if kind == 'unknown' and lower <= record['observed_at'] < upper:
                quality['excluded_reads'] += 1
        else:
            if active is None:
                reasons = set() if prior_kind == 'moving' else {prior_reason or 'start_unobserved'}
                active = {'first': sample, 'last': sample, 'count': 0, 'reasons': reasons, 'max_gap': 0}
            last = active['last']
            soc, old_soc = state['soc'], last['state']['soc']
            if soc is None:
                active['reasons'].add('soc_missing')
            elif old_soc is not None and soc > old_soc:
                active['reasons'].add('soc_increase')
            active['max_gap'] = max(active['max_gap'], stamp - last['record']['state_time'])
            active['last'] = sample
            active['count'] += 1
        previous, prior_kind, prior_reason = sample, kind, reason
    close('end_unobserved')
    sessions.sort(key=lambda row: row['start_time'], reverse=True)
    return {'sessions': sessions, 'eligible_count': sum(row['eligible'] for row in sessions),
            'fragment_count': sum(not row['eligible'] for row in sessions), 'quality': quality,
            'gap_threshold_seconds': MAX_GAP_MS//1000, 'capacity_kwh': capacity}


class ParkingAnalytics:
    def __init__(self, archive, database=None):
        self.archive = archive
        self.database = database

    def query(self, scope, vehicle, start, end, capacity=None, *, context_days=0):
        lower, _ = day_bounds(start)
        _, upper = day_bounds(end)
        if not 0 < upper-lower <= 31*86400000:
            raise ValueError('请选择不超过 31 天的停车观察范围。')
        padding=context_days*86400000 if context_days else MAX_GAP_MS
        def samples():
            for record, raw in self.archive.iter_records(scope, vehicle, max(0,lower-padding), upper+padding):
                climate = raw.get('additionalVehicleStatus', {})
                climate = climate.get('climateStatus', {}) if isinstance(climate, dict) else {}
                inside = numeric(climate.get('interiorTemp'), -80, 100) if isinstance(climate, dict) else None
                inside_time = numeric(climate.get('temperatureUpdateTime'), 1, 9999999999999) if isinstance(climate, dict) else None
                yield {'record': record, 'state': decode(raw), 'location': parse_location(raw), 'inside_temp': inside, 'inside_time': inside_time}
        base_samples = list(samples())
        result = analyze_parking(base_samples, lower, upper, capacity)
        if self.database is not None:
            window = 31*86400000
            history = UsageEvents(self.database).between(vehicle, max(0, lower-window), upper+window)
            events = history['events']
            triples = [row for row in events if row['kind'] == 'trip_end']
            charges = [row for row in events if row['kind'] == 'charge_end']
            result.update(build_events(triples, charges, base_samples, lower, upper, capacity))
            result['orphan_sessions'] = [row for row in result['sessions'] if not any(
                # Events use collection time; legacy sessions use vehicle time.
                # Inclusive comparison also assigns single-point observations.
                (row['start']['observed_at'] <= event['end_time'] and
                 row['end']['observed_at'] >= event['start_time']) or
                (row['start_time'] == row['end_time'] and
                 row['start_time'] in (event['start_time'], event['end_time']))
                for event in result['events'])]
            result['orphan_count'] = len(result['orphan_sessions'])
        result.update(start_date=start, end_date=end)
        return result
