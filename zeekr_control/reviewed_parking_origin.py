"""Explicit historical origin reviews with source-checked parking and gap evidence."""
from .commute_tags import _distance
from .parking_origin import _point, _summary, _telemetry, MAX_PARKING_AGE_MS
from .parking_destination import _stationary
from .reviewed_parking_destination import _sample
from .usage_events import MAX_SUMMARY_BYTES, number


def reviewed_parking_origin(db, vehicle, event, current):
    meta = current.get('reviewed_start_parking')
    start = number(event.get('start_time'), 1, 32503680000000)
    if (event.get('kind') != 'trip_end' or event.get('partial') is not True
            or current.get('partial') is not True or start is None or current.get('start_time') != start
            or not isinstance(meta,dict) or type(meta.get('version')) is not int or meta['version'] != 1
            or meta.get('reviewed') is not True or meta.get('basis') != 'reviewed_historical_parking'
            or meta.get('event_id') != event.get('id') or meta.get('start_time') != start):
        return None
    previous_id = meta.get('previous_event_id')
    parked_time = number(meta.get('previous_parking_time'), 1, 32503680000000)
    if not isinstance(previous_id,str) or previous_id == event['id'] or parked_time is None:
        return None
    row = db.execute("SELECT summary FROM monitor_events WHERE vehicle=? AND id=? AND kind='trip_end' "
                     'AND length(CAST(summary AS BLOB))<=?', (vehicle, previous_id, MAX_SUMMARY_BYTES)).fetchone()
    if row is None:
        return None
    previous = _summary(row[0])
    end = number(previous.get('end_time'), 1, 32503680000000)
    if (end is None or not end < parked_time < start or parked_time-end > 900000
            or start-end > MAX_PARKING_AGE_MS):
        return None
    departure, parked = _telemetry(current,'start'), _telemetry(previous,'parking')
    odometer = number(departure.get('odometer'))
    if odometer is None or not _stationary(departure,start,odometer) or not _stationary(parked,parked_time,odometer):
        return None
    if db.execute("SELECT 1 FROM monitor_events WHERE vehicle=? AND kind IN ('trip_start','trip_end') "
                  'AND id NOT IN (?,?) AND created>? AND created<? LIMIT 1',
                  (vehicle,event['id'],previous_id,end,start)).fetchone():
        return None
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_observations'").fetchone():
        return None
    states = db.execute('SELECT state_time,observed_at,CASE WHEN length(CAST(normalized_payload AS BLOB))<=? '
                        'THEN normalized_payload END FROM report_observations WHERE vehicle=? '
                        'AND state_time>=? AND state_time<=? ORDER BY state_time LIMIT 257',
                        (MAX_SUMMARY_BYTES,vehicle,parked_time,start)).fetchall()
    if not states or len(states)>256 or states[0][0]!=parked_time or states[-1][0]!=start:
        return None
    for stamp, observed, encoded in states:
        payload = _summary(encoded)
        if payload.get('observed_at') != observed or not _stationary(payload,stamp,odometer):
            return None
    anchor, old = _sample(db,vehicle,start), _sample(db,vehicle,parked_time)
    if anchor is None or old is None or _distance(anchor,old)>15:
        return None
    rows = db.execute('SELECT state_time,observed_time,location FROM observations WHERE vehicle=? '
                      'AND state_time>=? AND state_time<=? ORDER BY state_time,observed_time DESC,id DESC LIMIT 257',
                      (vehicle,end,start)).fetchall()
    if len(rows)>256:
        return None
    times = []
    for stamp, observed, encoded in rows:
        point = _point(_summary(encoded))
        if (point is None or number(observed,1,32503680000000) is None
                or not stamp <= observed <= stamp+60000 or _distance(anchor,point)>15):
            return None
        times.append(stamp)
    times = sorted(set(times))
    if len(times)<2 or times[0]!=end or times[-1]!=start:
        return None
    gap = max(b-a for a,b in zip(times,times[1:]))/1000
    return dict(source='parking_inferred',basis='reviewed_historical_parking',reviewed=True,
                point=anchor,sample_time=start,previous_event_id=previous_id,
                previous_end_time=end,previous_parking_time=parked_time,location_samples=len(times),
                sampling_gap_seconds=round(gap,3) if gap>180 else 0)
