"""Read-only destination estimates from a bounded, corroborated parking interval."""
from .commute_tags import _distance
from .parking_origin import _point, _summary, _telemetry
from .usage_events import MAX_SUMMARY_BYTES, number


MIN_PARKING_MS = 60000
MAX_PARKING_MS = 900000
MAX_GAP_MS = 180000
MAX_SAMPLES = 256


def _stationary(payload, stamp, odometer):
    observed = number(payload.get('observed_at'), 1, 32503680000000)
    speed = payload.get('speed')
    return (payload.get('state_time') == stamp and observed is not None
            and stamp <= observed <= stamp+60000 and payload.get('off') is True
            and number(payload.get('odometer')) == odometer
            and (speed is None or number(speed) == 0))


def _continuous(stamps, start, end):
    stamps = sorted(set(stamps))
    return (len(stamps) >= 2 and stamps[0] == start and stamps[-1] == end
            and all(b-a <= MAX_GAP_MS for a,b in zip(stamps,stamps[1:])))


def parking_destination(db, vehicle, event):
    """Estimate only the displayed place; preserve raw GPS and commute evidence.

    Repeated coordinates alone cannot establish parking. Both telemetry streams
    must advance through the same stopped interval with unchanged mileage. The
    location remains an estimate even when these independent state checks pass.
    """
    end = number(event.get('end_time'), 1, 32503680000000)
    if end is None or event.get('partial') is not False or event.get('kind') != 'trip_end':
        return None
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_observations'").fetchone():
        return None
    row = db.execute('SELECT summary FROM monitor_events WHERE vehicle=? AND id=? '
                     'AND length(CAST(summary AS BLOB))<=?',
                     (vehicle, event['id'], MAX_SUMMARY_BYTES)).fetchone()
    if row is None:
        return None
    current = _summary(row[0])
    arrival, parked = _telemetry(current, 'end'), _telemetry(current, 'parking')
    stamp = number(parked.get('state_time'), 1, 32503680000000)
    odometer = number(arrival.get('odometer'))
    anchor = _point(current.get('end_location'))
    if (current.get('partial') is not False or current.get('end_time') != end
            or stamp is None or not MIN_PARKING_MS <= stamp-end <= MAX_PARKING_MS
            or odometer is None or anchor is None
            or not _stationary(arrival, end, odometer) or not _stationary(parked, stamp, odometer)):
        return None
    if db.execute("SELECT 1 FROM monitor_events WHERE vehicle=? AND kind='trip_start' "
                  'AND created>? AND created<=? LIMIT 1', (vehicle, end, stamp)).fetchone():
        return None
    rows = db.execute('SELECT state_time,observed_at,CASE WHEN length(CAST(normalized_payload AS BLOB))<=? '
                      'THEN normalized_payload END FROM report_observations WHERE vehicle=? '
                      'AND state_time>=? AND state_time<=? ORDER BY state_time LIMIT ?',
                      (MAX_SUMMARY_BYTES, vehicle, end, stamp, MAX_SAMPLES+1)).fetchall()
    if len(rows) > MAX_SAMPLES:
        return None
    times = []
    for time, observed, encoded in rows:
        payload = _summary(encoded)
        if observed != payload.get('observed_at') or not _stationary(payload, time, odometer):
            return None
        times.append(time)
    if not _continuous(times, end, stamp):
        return None
    rows = db.execute('SELECT state_time,observed_time,location FROM observations WHERE vehicle=? '
                      'AND state_time>=? AND state_time<=? ORDER BY state_time,observed_time DESC,id DESC LIMIT ?',
                      (vehicle, end, stamp, MAX_SAMPLES+1)).fetchall()
    if len(rows) > MAX_SAMPLES:
        return None
    locations = []
    point = None
    for time, observed, encoded in rows:
        point = _point(_summary(encoded))
        if (point is None or number(observed, 1, 32503680000000) is None
                or not time <= observed <= time+60000 or _distance(point, anchor) > 15):
            return None
        locations.append(time)
    if not _continuous(locations, end, stamp):
        return None
    return dict(source='parking_inferred', point=point, sample_time=stamp,
                parking_seconds=round((stamp-end)/1000, 3),
                stationary_samples=len(set(times)), location_samples=len(set(locations)))
