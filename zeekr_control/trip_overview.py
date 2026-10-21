"""Seven-day travel aggregates over existing corrected local evidence only."""
import hashlib
import math
from statistics import median

from .tracks import day_bounds
from .usage_reports import date_label

DAY = 86400000


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def resolved(place):
    return (isinstance(place, dict) and bool(place.get('key')) and
            place.get('source') != 'unknown' and place.get('decision') != 'rejected' and
            not set(place.get('issues', ())) & {'missing_name', 'missing_position', 'candidate_conflict', 'adjacent_conflict'})


def statistics_key(place):
    return place.get('statistics_key') or place['key']


def union(intervals):
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return result


def parking_intervals(row, lower, upper):
    """Only confirmed observed portions; missing/truncated gaps remain unknown."""
    start, end = row.get('start_time'), row.get('end_time')
    quality = row.get('observation_quality') or {}
    unknown = quality.get('unknown_seconds')
    if (row.get('parking_status') != 'parked' or not finite(start) or not finite(end) or
            not finite(unknown) or quality.get('gaps_limited') or end <= start):
        return [], True
    gaps = union((max(start, g['start_time']), min(end, g['end_time']))
                 for g in row.get('observation_gaps', [])
                 if finite(g.get('start_time')) and finite(g.get('end_time')))
    if abs(sum(b-a for a, b in gaps)/1000 - unknown) > 1:
        return [], True
    intervals, cursor = [], start
    for a, b in gaps + [[end, end]]:
        intervals.append((max(cursor, lower), min(a, upper)))
        cursor = max(cursor, b)
    return union(intervals), bool(unknown)


def summarize(records, date, now):
    day_start, upper = day_bounds(date)
    lower = day_start - 6 * DAY
    end = min(upper, now + 1)
    days = [dict(date=date_label(lower+i*DAY), distance_km=None, duration_seconds=None,
                 trip_count=0, missing_distance_count=0, partial_count=0,
                 future=lower+i*DAY > now) for i in range(7)]
    by_date = {d['date']: d for d in days}
    routes, places = {}, {}
    unknown_routes = unknown_arrivals = count = 0
    distances = []

    def location(place):
        key = statistics_key(place)
        if key not in places:
            places[key] = dict(key=key, label=place.get('label') or '未命名地点', arrivals=0,
                               dates=set(), intervals=[], parking_incomplete=False)
        return places[key]

    seen = set()
    for row in records:
        identity = (row.get('type'), row.get('id'))
        if identity in seen:
            continue
        seen.add(identity)
        start, finish = row.get('start_time'), row.get('end_time')
        if not finite(finish) or finish > now:
            continue
        if row.get('type') == 'parking':
            place = row.get('end_place')
            if resolved(place) and finite(start) and finish > lower and start < end:
                item = location(place)
                intervals, incomplete = parking_intervals(row, lower, end)
                item['intervals'].extend(intervals)
                item['parking_incomplete'] |= incomplete
            continue
        if row.get('type') != 'trip' or not lower <= finish < end:
            continue
        day = by_date[date_label(finish)]
        count += 1
        day['trip_count'] += 1
        day['partial_count'] += bool(row.get('partial'))
        km = row.get('distance_km')
        if finite(km):
            day['distance_km'] = (day['distance_km'] or 0) + km
            distances.append(km)
        else:
            day['missing_distance_count'] += 1
        seconds = row.get('duration_seconds')
        if finite(seconds):
            day['duration_seconds'] = (day['duration_seconds'] or 0) + seconds
        a, b = row.get('start_place'), row.get('end_place')
        if resolved(b):
            item = location(b)
            item['arrivals'] += 1
            item['dates'].add(day['date'])
        else:
            unknown_arrivals += 1
        if not resolved(a) or not resolved(b):
            unknown_routes += 1
            continue
        a_key, b_key = statistics_key(a), statistics_key(b)
        pair = tuple(sorted((a_key, b_key)))
        if pair not in routes:
            labels = {a_key: a.get('label') or '未命名地点', b_key: b.get('label') or '未命名地点'}
            routes[pair] = dict(key=hashlib.sha256('|'.join(pair).encode()).hexdigest(),
                                label=(' ↔ '.join(labels[k] for k in pair) if pair[0] != pair[1]
                                       else labels[pair[0]]+'出发并返回'),
                                count=0, distances=[], durations=[], dates=set())
        route = routes[pair]
        route['count'] += 1
        route['dates'].add(day['date'])
        if finite(km):
            route['distances'].append(km)
        if finite(seconds):
            route['durations'].append(seconds)
    for route in routes.values():
        route['median_distance_km'] = median(route.pop('distances')) if route['distances'] else None
        route['median_duration_seconds'] = median(route.pop('durations')) if route['durations'] else None
        route.pop('distances', None)
        route.pop('durations', None)
        route['dates'] = sorted(route['dates'])
    for place in places.values():
        intervals = union(place.pop('intervals'))
        place['observed_parking_seconds'] = sum(b-a for a, b in intervals)/1000 if intervals else None
        place['dates'] = sorted(place['dates'])
    for day in days:
        if day['distance_km'] is not None:
            day['distance_km'] = round(day['distance_km'], 6)
    return dict(start_date=days[0]['date'], end_date=date, days=days, trip_count=count,
                distance_km=round(sum(distances), 6) if distances else None,
                unknown_route_count=unknown_routes, unknown_arrivals=unknown_arrivals,
                routes=sorted(routes.values(), key=lambda r: (-r['count'], r['key'])),
                places=sorted(places.values(), key=lambda p: (-p['arrivals'], p['key'])))


class TripOverview:
    def __init__(self, timeline):
        self.timeline = timeline

    def query(self, scope, vehicle, date, owner=None, now=None):
        import time
        now = int(time.time()*1000) if now is None else now
        lower, _ = day_bounds(date)
        start = date_label(lower-6*DAY)
        records, meta = self.timeline._records(scope, vehicle, owner or scope, start, date)
        result = summarize(records, date, now)
        result['history_quality'] = meta.get('history_quality', 0)
        return result
