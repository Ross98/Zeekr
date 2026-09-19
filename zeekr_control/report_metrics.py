"""Reproducible calculations for v2 reports."""
from statistics import median


def trip_metrics(start, end, samples, profile, *, partial=False, charge_overlap=False):
    distance = end.get('odometer') - start.get('odometer') if None not in (start.get('odometer'), end.get('odometer')) else None
    if distance is not None and distance < 0:
        distance, partial = None, True
    duration = (end['state_time'] - start['state_time']) / 1000 if None not in (start.get('state_time'), end.get('state_time')) else None
    if duration is not None and duration < 0:
        duration, partial = None, True
    delta = end.get('soc') - start.get('soc') if None not in (start.get('soc'), end.get('soc')) else None
    capacity = profile.get('battery_capacity_kwh')
    used = capacity * -delta / 100 if capacity and delta is not None and delta <= 0 and not charge_overlap else None
    consumption = used / distance * 100 if used is not None and distance is not None and distance >= 10 and -delta >= 3 and not partial else None
    speeds = [s.get('speed') for s in samples if s.get('speed') is not None]
    state_gaps = [b['state_time'] - a['state_time'] for a, b in zip(samples, samples[1:]) if None not in (a.get('state_time'), b.get('state_time'))]
    observed_gaps = [b['observed_at'] - a['observed_at'] for a, b in zip(samples, samples[1:])]
    range_delta = end.get('range_km') - start.get('range_km') if None not in (start.get('range_km'), end.get('range_km')) else None
    average_speed = distance / (duration / 3600) if distance is not None and duration and duration > 0 else None
    if average_speed is not None and not 0 <= average_speed <= 400: average_speed = None
    rated = profile.get('range_km')
    attainment = distance/(rated*(-delta)/100)*100 if consumption is not None and rated and delta < 0 else None
    def temp(metric):
        left, right = start.get(metric, {}), end.get(metric, {})
        valid = all(x.get('validity') == 'valid' and x.get('field_time') is not None for x in (left,right))
        return (right.get('value')-left.get('value')) if valid and right['field_time'] >= left['field_time'] else None
    tyre_changes = []
    for left, right in zip(start.get('tyres', []), end.get('tyres', [])):
        p1,p2 = left['pressure'],right['pressure']; t1,t2 = left['temperature'],right['temperature']
        tyre_changes.append({'position': left['position'],
            'pressure_delta': p2['value']-p1['value'] if p1['validity']=='valid' and p2['validity']=='valid' and p1['value'] and p2['value'] else None,
            'temperature_delta': t2['value']-t1['value'] if t1['validity']=='valid' and t2['validity']=='valid' else None})
    return {'distance_km': distance, 'duration_seconds': duration, 'soc_delta': delta,
            'range_delta_km': range_delta, 'estimated_kwh': used, 'estimated_kwh_100km': consumption,
            'range_attainment_percent': attainment, 'average_speed_kmh': average_speed,
            'sampled_max_speed_kmh': max(speeds) if speeds else None, 'speed_samples': len(speeds),
            'inside_temp_delta': temp('inside_temp'), 'outside_temp_delta': temp('outside_temp'),
            'outside_temp_average': ((start['outside_temp']['value']+end['outside_temp']['value'])/2
                if temp('outside_temp') is not None else None), 'tyre_changes': tyre_changes,
            'observation_count': len(samples),
            'max_state_gap_seconds': max(state_gaps)/1000 if state_gaps else None,
            'max_observed_gap_seconds': max(observed_gaps)/1000 if observed_gaps else None,
            'max_gap_seconds': max(state_gaps+observed_gaps)/1000 if state_gaps or observed_gaps else None,
            'partial': partial, 'charge_overlap': charge_overlap}


def charge_metrics(start, end, samples, profile, *, partial=False):
    window = (end['state_time'] - start['state_time']) / 1000
    if window < 0: window,partial=None,True
    valid = [s for s in samples if s.get('charging') is True and s.get('power_kw') is not None]
    area = seconds = active_seconds = 0
    intervals = []
    for left, right in zip(samples, samples[1:]):
        gap = (right['state_time'] - left['state_time']) / 1000
        observed_gap = (right['observed_at'] - left['observed_at']) / 1000
        if 0 < gap <= 180 and 0 <= observed_gap <= 180:
            if left.get('charging') is True and right.get('charging') is True:
                active_seconds += gap
            if (left.get('charging') is True and right.get('charging') is True
                    and left.get('power_kw') is not None and right.get('power_kw') is not None
                    and left.get('charging_mode') == right.get('charging_mode')):
                interval_area = (left['power_kw'] + right['power_kw']) / 2 * gap
                area += interval_area; seconds += gap
                intervals.append((left['state_time'], right['state_time'], interval_area, gap))
    coverage = seconds / window if window is not None and window > 0 else 0
    average = area / seconds if len(valid) >= 3 and seconds >= 120 and coverage >= .8 else None
    delta = end.get('soc') - start.get('soc') if None not in (start.get('soc'), end.get('soc')) else None
    capacity = profile.get('battery_capacity_kwh')
    state_gaps=[b['state_time']-a['state_time'] for a,b in zip(samples,samples[1:])]
    observed_gaps=[b['observed_at']-a['observed_at'] for a,b in zip(samples,samples[1:])]
    stop_state_gap = stop_observed_gap = None
    if len(samples) >= 2:
        stop_state_gap = (samples[-1]['state_time']-samples[-2]['state_time'])/1000
        stop_observed_gap = (samples[-1]['observed_at']-samples[-2]['observed_at'])/1000
    tail_drop = None
    if not partial and window is not None and window > 0:
        edge = window*.2
        front = [x for x in intervals if x[0] >= start['state_time'] and x[1] <= start['state_time']+edge*1000]
        tail = [x for x in intervals if x[0] >= end['state_time']-edge*1000 and x[1] <= end['state_time']]
        def segment(rows):
            duration = sum(x[3] for x in rows)
            return sum(x[2] for x in rows)/duration if len(rows) >= 2 and duration >= 120 and duration/edge >= .8 else None
        first,last = segment(front),segment(tail)
        if first and last is not None and (first-last)/first >= .2: tail_drop=(first-last)/first*100
    return {'duration_seconds': window, 'soc_delta': delta,
            'range_delta_km': end.get('range_km')-start.get('range_km') if None not in (start.get('range_km'),end.get('range_km')) else None,
            'estimated_kwh': capacity * delta / 100 if capacity and delta is not None and delta >= 0 else None,
            'sampled_peak_kw': max((s['power_kw'] for s in valid), default=None),
            'average_power_kw': average, 'power_sample_count': len(valid),
            'power_covered_seconds': seconds, 'power_coverage': coverage,
            'charging_time_covered_seconds': active_seconds,
            'charging_time_coverage': active_seconds/window if window is not None and window > 0 else 0,
            'max_state_gap_seconds': max(state_gaps)/1000 if state_gaps else None,
            'max_observed_gap_seconds': max(observed_gaps)/1000 if observed_gaps else None,
            'max_gap_seconds': max(state_gaps+observed_gaps)/1000 if state_gaps or observed_gaps else None,
            'stop_detection_state_gap_seconds': stop_state_gap,
            'stop_detection_observed_gap_seconds': stop_observed_gap,
            'tail_power_drop_percent': tail_drop, 'partial': partial}


def historical_median(values):
    values = [v for v in values if type(v) in (int, float)]
    return median(values) if len(values) >= 5 else None
