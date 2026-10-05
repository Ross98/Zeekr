"""Find stationary intervals outside saved trips and charges; preserve source records."""
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
    'unknown': '停车期间充电状态不明',
    'location': '位置观测不足，停车状态待确认',
}


def time_advances(record, previous):
    """Vehicle time, not equal telemetry values or a repeat label, proves a new observation."""
    if previous is None:
        return False
    current, old = record.get('state_time'), previous.get('state_time')
    return (type(current) in (int, float) and type(old) in (int, float)
            and current > old)


def location_key(sample):
    location = sample.get('location') or {}
    if location.get('valid') and location.get('latitude') is not None and location.get('longitude') is not None:
        return (location['latitude'], location['longitude'], location.get('coordinate_system'))
    return None


def build_events(trips, charges, samples, lower, upper, capacity=None):
    """Trip/charge windows override GPS; observation quality gates energy separately."""
    capacity = numeric(capacity, .001, 1000)
    trips = sorted((row for row in trips if row.get('kind') == 'trip_end' and
                    isinstance(row.get('start_time'), (int, float)) and
                    isinstance(row.get('end_time'), (int, float))),
                   key=lambda row: (row['start_time'], row['end_time']))
    ordered = sorted(samples, key=lambda row: row['record']['observed_at'])
    samples = []
    for row in ordered:
        record = row['record']
        if (record.get('change') == 'repeat' and not record.get('flags')
                and not time_advances(record, samples[-1]['record'] if samples else None)):
            continue
        if (record.get('change') == 'revision' and not record.get('flags') and samples and
                record.get('state_time') == samples[-1]['record'].get('state_time')):
            samples[-1] = row
        else:
            samples.append(row)
    # Saved trip intervals take priority over stationary GPS (traffic lights included).
    # Remove charge intervals before checking location; charge time never enters parking.
    windows = []
    cursor = lower
    previous_trip = None
    for trip in trips:
        if trip['end_time'] <= lower:
            previous_trip = trip
            continue
        if trip['start_time'] >= upper:
            windows.append((cursor, trip['start_time'], previous_trip, trip))
            cursor = upper
            break
        if trip['start_time'] > cursor:
            windows.append((cursor, trip['start_time'], previous_trip, trip))
        cursor = max(cursor, trip['end_time'])
        previous_trip = trip
    if cursor < upper:
        windows.append((cursor, upper, previous_trip, None))
    excluded = [(row.get('start_time') or lower, row['end_time']) for row in charges
                if row.get('end_time') is not None]
    for index, row in enumerate(samples):
        if row['state'].get('charging') is True:
            excluded.append((row['record']['observed_at'],
                             samples[index+1]['record']['observed_at'] if index+1 < len(samples) else upper))
    intervals = []
    for start, end, before, after in windows:
        pieces = [(start, end)]
        for a, b in sorted(excluded):
            pieces = [(x, y) for left, right in pieces for x, y in
                      ([(left, right)] if b <= left or a >= right else
                       [(left, min(a, right)), (max(b, left), right)]) if y > x]
        for left, right in pieces:
            within = [row for row in samples if left <= row['record']['observed_at'] <= right
                      and row['state'].get('charging') is not True]
            if not within:
                continue
            # A changed coordinate ends a stationary run; missing coordinates are
            # retained as energy-quality evidence, never invented or interpolated.
            runs, run, position = [], [], None
            for row in within:
                current = location_key(row)
                if current is not None and position is not None and current != position:
                    runs.append(run)
                    run = []
                run.append(row)
                if current is not None:
                    position = current
            if run:
                runs.append(run)
            for index, run in enumerate(runs):
                a = left if index == 0 else run[0]['record']['observed_at']
                b = right if index == len(runs)-1 else run[-1]['record']['observed_at']
                open_end = after is None and right == end
                if open_end:
                    b = min(b, run[-1]['record']['observed_at'])
                if b > a and b > lower and a < upper:
                    intervals.append((a, b, before, after, run, open_end,
                                      left != start or right != end or len(runs) > 1))
    events = []
    for start, end, before, after, within, open_end, clipped in intervals:
        positions = [location_key(row) for row in within if location_key(row) is not None]
        stationary = len(positions) >= 2 and len(set(positions)) == 1
        parked = [row for row in within if not row['record'].get('flags')
                  and row['record'].get('state_time') is not None]
        reasons = set()
        if clipped or before is None or after is None or before.get('partial') or after.get('partial'):
            reasons.add('boundary')
        if not parked or parked[0]['record']['observed_at'] - start > MAX_GAP_MS or end - parked[-1]['record']['observed_at'] > MAX_GAP_MS:
            reasons.add('observations')
        timed = [start] + [row['record']['observed_at'] for row in within] + [end]
        if any(b-a > MAX_GAP_MS for a, b in zip(timed, timed[1:])):
            reasons.add('gap')
        if not stationary:
            reasons.add('location')
        if any(row['state'].get('charging') is None for row in within):
            reasons.add('unknown')
        if any(row['record'].get('flags') or row['record'].get('change') == 'regression' or
               row['record'].get('state_time') is None
               for row in within):
            reasons.add('invalid')
        vehicle_times = [row['record'].get('state_time') for row in within]
        if any(a is not None and b is not None and (b < a or b-a > MAX_GAP_MS)
               for a,b in zip(vehicle_times,vehicle_times[1:])):
            reasons.add('invalid')
        socs = [row['state'].get('soc') for row in parked]
        boundary_socs = [before.get('end_soc') if before and start == before['end_time'] else within[0]['state'].get('soc'),
                         after.get('start_soc') if after and end == after['start_time'] else within[-1]['state'].get('soc')]
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
        events.append({'id': (before['id'] if before else 'range') + ':' + (after['id'] if after else 'open') + ':' + str(start), 'start_time': start,
                       'end_time': end, 'duration_seconds': duration, 'category': category,
                       'start_trip_id': before['id'] if before else None, 'end_trip_id': after['id'] if after else None,
                       'start_soc': boundary_socs[0], 'end_soc': boundary_socs[1],
                       'soc_drop': drop, 'estimated_kwh': round(drop*capacity/100, 4) if drop is not None and capacity else None,
                       'status': 'comparable' if not reasons else 'uncertain', 'open': open_end,
                       'parking_status': 'parked' if stationary else 'candidate',
                       'p_gear_samples': sum(row['state'].get('gear') == 'P' for row in parked),
                       'reasons': sorted(reasons), 'reason_labels': [LABELS[key] for key in sorted(reasons)],
                       'sample_count': len(within), 'gap_count': sum(b-a > MAX_GAP_MS for a, b in zip(timed, timed[1:]))})
    events.sort(key=lambda row: row['start_time'], reverse=True)
    return {'events': events, 'parking_count': sum(row['parking_status'] == 'parked' for row in events), 'comparable_count': sum(row['status'] == 'comparable' for row in events),
            'uncertain_count': sum(row['status'] == 'uncertain' for row in events),
            'calculation_version': 3}
