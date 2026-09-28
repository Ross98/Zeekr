"""Reconstruct parking candidates from saved trips without changing source records."""
from datetime import datetime

from .snapshot_archive import BEIJING
from .vehicle_state import numeric


MAX_GAP_MS = 600000
LABELS = {
    'gap': '停车期间有超过 10 分钟的数据缺口',
    'charging': '停车期间有充电记录或充电状态',
    'movement': '停车期间有移动或里程变化证据',
    'invalid': '停车期间有异常时间或无效观测',
    'soc': '起止电量缺失或停车期间电量回升',
    'boundary': '缺少可靠的停车起止边界',
    'observations': '停车起止附近缺少有效观测',
    'unknown': '停车期间动力、速度或充电状态不明',
}


def build_events(trips, charges, samples, lower, upper, capacity=None):
    """Return one candidate per adjacent saved trip pair; evidence gates energy only."""
    capacity = numeric(capacity, .001, 1000)
    trips = sorted((row for row in trips if row.get('kind') == 'trip_end' and
                    isinstance(row.get('start_time'), (int, float)) and
                    isinstance(row.get('end_time'), (int, float))),
                   key=lambda row: (row['start_time'], row['end_time']))
    ordered = sorted(samples, key=lambda row: row['record']['observed_at'])
    samples = []
    for row in ordered:
        record = row['record']
        if record.get('change') == 'repeat' and not record.get('flags'):
            continue
        if (record.get('change') == 'revision' and not record.get('flags') and samples and
                record.get('state_time') == samples[-1]['record'].get('state_time')):
            samples[-1] = row
        else:
            samples.append(row)
    events = []
    for before, after in zip(trips, trips[1:]):
        start, end = before['end_time'], after['start_time']
        if end <= start or end <= lower or start >= upper:
            continue
        within = [row for row in samples if start <= row['record']['observed_at'] <= end]
        odometers = [row['state'].get('km') for row in within if row['state'].get('km') is not None]
        stable_odometer = len(odometers) >= 2 and len(set(odometers)) == 1
        parked = [row for row in within if row['state'].get('off') is True and
                  (row['state'].get('speed') == 0 or
                   row['state'].get('speed') is None and stable_odometer) and
                  row['state'].get('charging') is False and
                  not row['record'].get('flags') and row['record'].get('state_time') is not None]
        reasons = set()
        if before.get('partial') or after.get('partial'):
            reasons.add('boundary')
        if not parked or parked[0]['record']['observed_at'] - start > MAX_GAP_MS or end - parked[-1]['record']['observed_at'] > MAX_GAP_MS:
            reasons.add('observations')
        timed = [start] + [row['record']['observed_at'] for row in within] + [end]
        if any(b-a > MAX_GAP_MS for a, b in zip(timed, timed[1:])):
            reasons.add('gap')
        if any(row.get('end_time') is not None and start < row['end_time'] <= end and
               (row.get('start_time') is None or row['start_time'] < end)
               for row in charges):
            reasons.add('charging')
        if any(row['state'].get('charging') is True for row in within):
            reasons.add('charging')
        if any(row['state'].get('charging') is None or row['state'].get('off') is None or
               row['state'].get('speed') is None and not stable_odometer for row in within):
            reasons.add('unknown')
        if any(row['record'].get('flags') or row['record'].get('change') == 'regression' or
               row['record'].get('state_time') is None
               for row in within):
            reasons.add('invalid')
        vehicle_times = [row['record'].get('state_time') for row in within]
        if any(a is not None and b is not None and (b < a or b-a > MAX_GAP_MS)
               for a,b in zip(vehicle_times,vehicle_times[1:])):
            reasons.add('invalid')
        if any(row['state'].get('off') is False or
               (row['state'].get('speed') is not None and row['state']['speed'] > 0)
               for row in within):
            reasons.add('movement')
        if len(set(odometers)) > 1:
            reasons.add('movement')
        socs = [row['state'].get('soc') for row in parked]
        boundary_socs = [before.get('end_soc'), after.get('start_soc')]
        if any(value is None for value in boundary_socs) or any(value is None for value in socs):
            reasons.add('soc')
        elif any(b > a for a, b in zip([boundary_socs[0]] + socs,
                                        socs + [boundary_socs[1]])):
            reasons.add('soc')
        drop = round(boundary_socs[0] - boundary_socs[1], 6) if not reasons else None
        duration = (end-start)/1000
        category = ('multi_day' if duration >= 86400 else 'overnight' if
                    datetime.fromtimestamp(start/1000, BEIJING).date() !=
                    datetime.fromtimestamp(end/1000, BEIJING).date() else 'same_day')
        events.append({'id': before['id'] + ':' + after['id'], 'start_time': start,
                       'end_time': end, 'duration_seconds': duration, 'category': category,
                       'start_trip_id': before['id'], 'end_trip_id': after['id'],
                       'start_soc': boundary_socs[0], 'end_soc': boundary_socs[1],
                       'soc_drop': drop, 'estimated_kwh': round(drop*capacity/100, 4) if drop is not None and capacity else None,
                       'status': 'comparable' if not reasons else 'uncertain', 'open': False,
                       'reasons': sorted(reasons), 'reason_labels': [LABELS[key] for key in sorted(reasons)],
                       'sample_count': len(within), 'gap_count': sum(b-a > MAX_GAP_MS for a, b in zip(timed, timed[1:]))})
    if trips:
        last = trips[-1]
        start = last['end_time']
        following = [row for row in samples if start <= row['record']['observed_at'] < upper]
        parked = [row for row in following if row['state'].get('off') is True and
                  row['state'].get('speed') == 0 and row['state'].get('charging') is False]
        if start < upper and parked and parked[-1]['record']['observed_at'] >= lower:
            end = parked[-1]['record']['observed_at']
            if end > start:
                duration = (end-start)/1000
                category = ('multi_day' if duration >= 86400 else 'overnight' if
                            datetime.fromtimestamp(start/1000, BEIJING).date() !=
                            datetime.fromtimestamp(end/1000, BEIJING).date() else 'same_day')
                events.append({'id': last['id'] + ':open', 'start_time': start, 'end_time': end,
                               'duration_seconds': duration, 'category': category,
                               'start_trip_id': last['id'], 'end_trip_id': None,
                               'start_soc': last.get('end_soc'), 'end_soc': parked[-1]['state'].get('soc'),
                               'soc_drop': None, 'estimated_kwh': None, 'status': 'uncertain',
                               'open': True, 'reasons': ['boundary'],
                               'reason_labels': ['后续行程未记录，停车结束边界未知'],
                               'sample_count': len(following), 'gap_count': 0})
    events.sort(key=lambda row: row['start_time'], reverse=True)
    return {'events': events, 'comparable_count': sum(row['status'] == 'comparable' for row in events),
            'uncertain_count': sum(row['status'] == 'uncertain' for row in events),
            'calculation_version': 2}
