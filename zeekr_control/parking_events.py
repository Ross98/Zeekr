"""Find stationary intervals outside saved trips; preserve source records."""
from datetime import datetime
from math import asin, cos, radians, sin, sqrt

from .snapshot_archive import BEIJING
from .vehicle_state import numeric
from .geocoding import is_trusted_location


MAX_GAP_MS = 600000
GPS_DRIFT_METERS = 15
LABELS = {
    'gap': '停车期间有超过 10 分钟的数据缺口',
    'charging': '充电阶段边界或观测不足，无法分离充电与耗电',
    'movement': '停车期间有移动或里程变化证据',
    'invalid': '停车期间有异常时间或无效观测',
    'soc': '电量观测缺失或阶段内 SOC 变化无法可靠分离',
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


def stationary_support(first, second):
    """Small coordinate changes need corroboration from both vehicle observations."""
    a, b = first['state'], second['state']
    return (a.get('km') is not None and a.get('km') == b.get('km')
            and all((state.get('off') is True or state.get('gear') == 'P')
                    and state.get('off') is not False
                    and state.get('gear') not in ('R', 'D')
                    and not (state.get('speed') is not None and state['speed'] > 0)
                    for state in (a, b)))


def same_position(first, second):
    """Compare against a fixed anchor, never a chain of nearby moving points."""
    a, b = location_key(first), location_key(second)
    if a is None or b is None or a[2] != b[2]:
        return False
    if a == b:
        return True
    if not stationary_support(first, second):
        return False
    lat1, lat2 = radians(a[0]), radians(b[0])
    distance = 2 * 6371000 * asin(min(1, sqrt(
        sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin(radians(b[1]-a[1])/2)**2)))
    return distance <= GPS_DRIFT_METERS


def charging_energy(charges, samples, start, end, boundary_socs):
    """Separate SOC gain during known charge phases from noncharging SOC loss.

    Exact endpoint observations are required; charge SOC gain is not input kWh.
    Missing/overlapping phases never imply zero consumption.
    """
    phases = []
    for charge in charges:
        a, b = charge.get('start_time'), charge.get('end_time')
        if b is None or b <= start or (a is not None and a >= end):
            continue
        phases.append({'start_time': a, 'end_time': b,
                       'duration_seconds': (b-a)/1000 if a is not None and b >= a else None,
                       'soc_gain': None})
    phases.sort(key=lambda row: row['start_time'] if row['start_time'] is not None else start)
    exact = {row['record']['observed_at']: row['state'].get('soc') for row in samples
             if not row['record'].get('flags') and row['record'].get('change') != 'regression'
             and row['record'].get('state_time') == row['record']['observed_at']}
    phase_known = True
    consumption_known = all(value is not None for value in boundary_socs)
    gain, previous = 0, start
    for phase in phases:
        a, b = phase['start_time'], phase['end_time']
        if (a is None or a < previous or b > end or b <= a
                or exact.get(a) is None or exact.get(b) is None or exact[b] < exact[a]):
            phase_known = False
        else:
            phase['soc_gain'] = round(exact[b]-exact[a], 6)
            gain += phase['soc_gain']
        previous = b
    uncovered_charge = any(row['state'].get('charging') is True and not any(
        phase['start_time'] is not None and phase['start_time'] <= row['record']['observed_at'] <= phase['end_time']
        for phase in phases) for row in samples)
    if uncovered_charge:
        phase_known = False
        phases.append({'start_time': None, 'end_time': None, 'duration_seconds': None, 'soc_gain': None})
    points = [(start, boundary_socs[0])] + [(row['record']['observed_at'], row['state'].get('soc')) for row in samples] + [(end, boundary_socs[1])]
    consumption = 0
    for (a, x), (b, y) in zip(points, points[1:]):
        if x is None or y is None:
            consumption_known = False
            continue
        inside = any(phase['start_time'] is not None and phase['end_time'] is not None
                     and phase['start_time'] <= a < b <= phase['end_time'] for phase in phases)
        if inside:
            if y < x:
                consumption_known = False
        elif y > x:
            consumption_known = False
        else:
            consumption += x-y
    return phases, round(gain, 6) if phase_known else None, consumption if phase_known and consumption_known else None


def build_events(trips, charges, samples, lower, upper, capacity=None):
    """Trip windows override GPS; observation quality gates energy separately."""
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
    # Reconstruct physical boundaries before applying the requested date filter.
    windows = []
    cursor = samples[0]['record']['observed_at'] if samples else lower
    previous_trip = None
    for trip in trips:
        if trip['start_time'] > cursor:
            windows.append((cursor, trip['start_time'], previous_trip, trip))
        cursor = max(cursor, trip['end_time']) if previous_trip else trip['end_time']
        previous_trip = trip
    if samples and cursor < samples[-1]['record']['observed_at']:
        windows.append((cursor, samples[-1]['record']['observed_at'], previous_trip, None))
    intervals = []
    for start, end, before, after in windows:
        if end <= lower or start >= upper:
            continue
        # Charging belongs to this stop; only movement can split location runs.
        left, right = start, end
        within = [row for row in samples if left <= row['record']['observed_at'] <= right]
        if not within:
            continue
        # Tolerate bounded GPS drift only with stationary vehicle evidence.
        # Missing coordinates remain quality evidence, never interpolated.
        runs, run, position = [], [], None
        for row in within:
            current = location_key(row)
            if current is not None and position is not None and (
                    not same_position(position, row) or
                    (location_key(position) != current and not stationary_support(run[-1], row))):
                runs.append(run)
                run = []
            run.append(row)
            if current is not None and (position is None or len(run) == 1):
                position = row
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
        positions = [row for row in within if location_key(row) is not None]
        stationary = len(positions) >= 2 and all(same_position(positions[0], row) for row in positions[1:])
        parked = [row for row in within if not row['record'].get('flags')
                  and row['record'].get('state_time') is not None]
        reasons = set()
        odometers = [row['state'].get('km') for row in within if row['state'].get('km') is not None]
        if (len(set(odometers)) > 1 or any(
                row['state'].get('gear') in ('R', 'D') or
                (row['state'].get('speed') is not None and row['state']['speed'] > 0)
                for row in within)):
            reasons.add('movement')
            stationary = False
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
        boundary_socs = [before.get('end_soc') if before and start == before['end_time'] else within[0]['state'].get('soc'),
                         after.get('start_soc') if after and end == after['start_time'] else within[-1]['state'].get('soc')]
        phases, gain, consumption = charging_energy(charges, within, start, end, boundary_socs)
        if gain is None:
            reasons.add('charging')
        if consumption is None:
            reasons.add('soc')
        drop = round(consumption, 6) if not reasons else None
        duration = (end-start)/1000
        category = ('multi_day' if duration >= 86400 else 'overnight' if
                    datetime.fromtimestamp(start/1000, BEIJING).date() !=
                    datetime.fromtimestamp(end/1000, BEIJING).date() else 'same_day')
        events.append({'id': (before['id'] if before else 'range') + ':' + (after['id'] if after else 'open') + ':' + str(start), 'start_time': start,
                       'end_time': end, 'duration_seconds': duration, 'category': category,
                       'start_trip_id': before['id'] if before else None, 'end_trip_id': after['id'] if after else None,
                       'start_soc': boundary_socs[0], 'end_soc': boundary_socs[1],
                       'charging_phases': phases, 'charged_soc_gain': gain,
                       'soc_drop': drop, 'estimated_kwh': round(drop*capacity/100, 4) if drop is not None and capacity else None,
                       'status': 'comparable' if not reasons else 'uncertain', 'open': open_end,
                       'parking_status': 'parked' if stationary else 'candidate',
                       'p_gear_samples': sum(row['state'].get('gear') == 'P' for row in parked),
                       'reasons': sorted(reasons), 'reason_labels': [LABELS[key] for key in sorted(reasons)],
                       'sample_count': len(within), 'gap_count': sum(b-a > MAX_GAP_MS for a, b in zip(timed, timed[1:])),
                       # Query resolves this private evidence to a name, then removes coordinates.
                       '_position': next((row['location'] for row in positions
                                          if row['location'].get('coordinate_system') == 'WGS84（社区解释）'), None),
                       '_location': next((row['location'] for row in parked
                                          if is_trusted_location(row.get('location')) and
                                          row['location']['coordinate_system'] == 'WGS84（社区解释）'), None)})
    events.sort(key=lambda row: row['start_time'], reverse=True)
    return {'events': events, 'parking_count': sum(row['parking_status'] == 'parked' for row in events), 'comparable_count': sum(row['status'] == 'comparable' for row in events),
            'uncertain_count': sum(row['status'] == 'uncertain' for row in events),
            'calculation_version': 5}
