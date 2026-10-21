"""Owner-scoped parking label references, without promoting untrusted GPS."""
from .commute_tags import _distance
from .parking_origin import _point, _summary
from .place_regions import contains
from .usage_events import number

MAX_AGE_MS = 180000
MAX_DISTANCE_M = 300
MAX_ROWS = 128


def parking_place_reference(db, vehicle, event, names, owner, regions, rule):
    """Use only prior trusted data plus a fresh, stable parked coordinate.

    Both coordinates must resolve to the same unambiguous saved naming region,
    including an existing commute alias. Missing observation time is not proof
    of fresh GPS. This returns label evidence only, never a trusted map point.
    """
    start = number(event.get('start_time'), 1, 32503680000000)
    end = number(event.get('end_time'), 1, 32503680000000)
    if (db is None or start is None or end is None or end < start or
            event.get('parking_status') != 'parked' or
            (event.get('p_gear_samples') or 0) < 2 or
            set(event.get('reasons', ())) & {'movement', 'location'}):
        return None
    rows = db.execute('SELECT state_time,observed_time,location FROM observations '
                      'WHERE vehicle=? AND state_time>=? AND state_time<=? '
                      'ORDER BY state_time,observed_time DESC,id DESC LIMIT ?',
                      (vehicle, start, min(end, start+MAX_AGE_MS), MAX_ROWS+1)).fetchall()
    if not rows or len(rows) > MAX_ROWS:
        return None
    anchor = None
    for stamp, observed, encoded in rows:
        raw = _summary(encoded)
        point = _point(raw)
        if (point is None or raw.get('trusted') is True or
                type(observed) not in (int, float) or not stamp <= observed <= stamp+90000):
            return None
        if anchor is None:
            anchor = point
        elif _distance(anchor, point) > 15:
            return None
    candidates = db.execute('SELECT state_time,observed_time,location FROM observations '
                            'WHERE vehicle=? AND state_time>=? AND state_time<? '
                            'ORDER BY state_time DESC,observed_time DESC,id DESC LIMIT ?',
                            (vehicle, start-MAX_AGE_MS, start, MAX_ROWS+1)).fetchall()
    if len(candidates) > MAX_ROWS:
        return None
    previous = None
    for stamp, observed, encoded in candidates:
        point = _point(_summary(encoded), trusted=True)
        if point is not None:
            if type(observed) not in (int,float) or not stamp <= observed <= stamp+90000:
                return None
            previous = (stamp, point)
            break
    if previous is None:
        return None
    stamp, point = previous
    distance = _distance(point, anchor)
    if distance > MAX_DISTANCE_M:
        return None
    probes = []
    for identity, coordinate in (('trusted',point),('parking',anchor)):
        if sum(contains(r['body'], coordinate) for r in regions) > 1:
            return None
        probes.append(dict(id=identity,latitude=coordinate[0],longitude=coordinate[1],label='未命名地点'))
    resolved = names.apply(owner, vehicle, dict(places=probes), rule)['places']
    a, b = resolved
    key = a.get('statistics_key') or ''
    if (not key.startswith('region:') or key != b.get('statistics_key') or
            any(p.get('candidate_conflict') or p.get('name_source') not in ('manual','commute') for p in resolved)):
        return None
    place = dict(latitude=anchor[0],longitude=anchor[1],label=b['label'],
                 name_source=b['name_source'],statistics_key=key)
    evidence = dict(source='parking_reference',reference_time=stamp,
                    sampling_gap_seconds=(start-stamp)/1000,distance_m=round(distance,1))
    return place, evidence
