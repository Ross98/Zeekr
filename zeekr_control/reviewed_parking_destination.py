"""Explicit historical parking reviews, separate from automatic trip inference."""
from .commute_tags import _distance
from .parking_origin import _point, _summary
from .usage_events import MAX_SUMMARY_BYTES, number


def _sample(db, vehicle, stamp, trusted=False):
    row = db.execute('SELECT observed_time,location FROM observations WHERE vehicle=? AND state_time=? '
                     'ORDER BY observed_time DESC,id DESC LIMIT 1', (vehicle, stamp)).fetchone()
    if row is None or number(row[0], 1, 32503680000000) is None or not stamp <= row[0] <= stamp+60000:
        return None
    return _point(_summary(row[1]), trusted=trusted)


def reviewed_parking_destination(db, vehicle, event, current):
    """Honor a reviewed fragment only while its scoped source evidence still fits.

    No mileage, complete-trip status or continuous coverage is inferred. Gaps
    stay explicit; actual observations determine both the point and gap length.
    """
    meta = current.get('reviewed_end_parking')
    end = number(event.get('end_time'), 1, 32503680000000)
    if (event.get('kind') != 'trip_end' or event.get('partial') is not True
            or current.get('partial') is not True or end is None or current.get('end_time') != end
            or not isinstance(meta, dict) or type(meta.get('version')) is not int or meta['version'] != 1
            or meta.get('reviewed') is not True or meta.get('basis') != 'reviewed_historical_parking'
            or meta.get('event_id') != event.get('id') or meta.get('end_time') != end):
        return None
    before = number(meta.get('previous_trusted_time'), 1, 32503680000000)
    after = number(meta.get('next_trusted_time'), 1, 32503680000000)
    if before is None or after is None or not 0 < end-before <= 900000:
        return None
    next_id = meta.get('next_event_id')
    if not isinstance(next_id, str) or next_id == event['id']:
        return None
    row = db.execute("SELECT summary FROM monitor_events WHERE vehicle=? AND id=? AND kind='trip_end' "
                     'AND length(CAST(summary AS BLOB))<=?', (vehicle, next_id, MAX_SUMMARY_BYTES)).fetchone()
    if row is None:
        return None
    next_start = number(_summary(row[0]).get('start_time'), 1, 32503680000000)
    if next_start is None or not 0 < next_start-end <= 3600000 or not 0 < after-next_start <= 180000:
        return None
    if db.execute("SELECT 1 FROM monitor_events WHERE vehicle=? AND kind IN ('trip_start','trip_end') "
                  'AND id NOT IN (?,?) AND created>? AND created<? LIMIT 1',
                  (vehicle, event['id'], next_id, end, next_start)).fetchone():
        return None
    anchor = _sample(db, vehicle, end)
    a, b = _sample(db, vehicle, before, True), _sample(db, vehicle, after, True)
    if anchor is None or a is None or b is None or max(_distance(anchor,a), _distance(anchor,b)) > 150:
        return None
    rows = db.execute('SELECT state_time,observed_time,location FROM observations WHERE vehicle=? '
                      'AND state_time>=? AND state_time<=? ORDER BY state_time,observed_time DESC,id DESC LIMIT 257',
                      (vehicle, end, next_start)).fetchall()
    if len(rows) > 256:
        return None
    times = []
    for stamp, observed, encoded in rows:
        point = _point(_summary(encoded))
        if (point is None or number(observed, 1, 32503680000000) is None
                or not stamp <= observed <= stamp+60000 or _distance(point,anchor) > 15):
            return None
        times.append(stamp)
    times = sorted(set(times))
    if len(times) < 2 or times[0] != end or times[-1]-end < 60000:
        return None
    boundaries = sorted(set([end, *times, next_start]))
    gap = max(b-a for a,b in zip(boundaries,boundaries[1:])) / 1000
    return dict(source='parking_inferred', basis='reviewed_historical_parking', reviewed=True,
                point=anchor, sample_time=end, location_samples=len(times),
                previous_trusted_time=before, next_trusted_time=after,
                sampling_gap_seconds=round(gap, 3) if gap > 180 else 0)
