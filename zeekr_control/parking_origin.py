"""Read-only parking-origin estimates; never promote them to trusted GPS samples."""
import json
import math

from .commute_tags import _distance
from .trip_place_geometry import RADIUS_M
from .usage_events import MAX_SUMMARY_BYTES, number
from .movement_barriers import trip_start_between
from .trip_visibility import visible_clause


MAX_PARKING_AGE_MS = 31 * 86400000


def _point(location, trusted=False):
    if not isinstance(location, dict):
        return None
    lat, lon = location.get('latitude'), location.get('longitude')
    if (location.get('valid') is not True or location.get('plottable') is not True
            or location.get('coordinate_system') != 'WGS84（社区解释）'
            or (trusted and location.get('trusted') is not True)
            or type(lat) not in (int, float) or type(lon) not in (int, float)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180 or (lat == 0 and lon == 0)):
        return None
    return lat, lon


def _summary(encoded):
    try:
        result = json.loads(encoded)
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError, RecursionError):
        return {}


def _telemetry(summary, side):
    report = summary.get('report_v2')
    value = report.get(side) if isinstance(report, dict) else None
    return value if isinstance(value, dict) else {}


def _previous_arrival(db, vehicle, identity, start):
    """Latest vehicle arrival or contradiction; never skip a bad newest row."""
    row = db.execute(
        'WITH encoded AS (SELECT id,created,('+visible_clause(db)+') AS visible, '
        'CASE WHEN length(CAST(summary AS BLOB))<=? '
        'THEN CASE WHEN json_valid(summary) THEN summary END END AS summary '
        "FROM monitor_events WHERE vehicle=? AND kind='trip_end' AND id!=?), "
        'timed AS (SELECT id,created,visible,summary, '
        "CASE WHEN json_type(summary,'$.end_time') IN ('integer','real') "
        "AND json_extract(summary,'$.end_time') BETWEEN 1 AND 32503680000000 "
        "THEN json_extract(summary,'$.end_time') END AS vehicle_end, "
        "CASE WHEN json_type(summary,'$.start_time') IN ('integer','real') "
        "AND json_extract(summary,'$.start_time') BETWEEN 1 AND 32503680000000 "
        "THEN json_extract(summary,'$.start_time') END AS vehicle_start FROM encoded) "
        'SELECT id,summary,visible FROM timed WHERE vehicle_end<? '
        'OR (vehicle_end IS NULL AND created<?) '
        'OR (vehicle_end>=? AND (vehicle_start<? OR (vehicle_start IS NULL AND created<?))) '
        'ORDER BY COALESCE(vehicle_end,created) DESC,created DESC,id DESC LIMIT 1',
        (MAX_SUMMARY_BYTES,vehicle,identity,start,start,start,start,start)).fetchone()
    # A hidden latest source is a stop, never permission to use an older trip.
    return row[:2] if row is not None and row[2] else None


def parking_origin(db, vehicle, event):
    """Corroborate a fresh predeparture coordinate with a parked previous arrival.

    An equal odometer is supporting evidence, not proof of continuous parking.
    Keep provenance explicit and retain original coordinates. Commute matching
    may use this corroborated estimate without promoting it to trusted GPS.
    A missing/invalid newest record is a stop.
    """
    start = number(event.get('start_time'), 1, 32503680000000)
    if event.get('partial') is True and event.get('kind') == 'trip_end':
        from .reviewed_parking_origin import reviewed_parking_origin
        row = db.execute('SELECT summary FROM monitor_events WHERE vehicle=? AND id=? '
                         'AND length(CAST(summary AS BLOB))<=?',
                         (vehicle,event['id'],MAX_SUMMARY_BYTES)).fetchone()
        return reviewed_parking_origin(db,vehicle,event,_summary(row[0])) if row else None
    if start is None or event.get('partial') is not False:
        return None
    current = db.execute('SELECT summary FROM monitor_events WHERE vehicle=? AND id=? '
                         'AND length(CAST(summary AS BLOB))<=?',
                         (vehicle, event['id'], MAX_SUMMARY_BYTES)).fetchone()
    if not current:
        return None
    current = _summary(current[0])
    departure = _telemetry(current, 'start')
    odo = number(departure.get('odometer'))
    origin = _point(current.get('start_location'))
    if (odo is None or origin is None or current.get('partial') is not False
            or current.get('start_time') != start
            or departure.get('state_time') != start):
        return None
    sample = db.execute('SELECT state_time,observed_time,location FROM observations '
                        'WHERE vehicle=? AND state_time>=? AND state_time<? '
                        'ORDER BY state_time DESC,observed_time DESC,id DESC LIMIT 1',
                        (vehicle, start-180000, start)).fetchone()
    if not sample:
        return None
    stamp, observed, encoded = sample
    point = _point(_summary(encoded))
    if (point is None or number(observed, 1, 32503680000000) is None or not stamp <= observed <= stamp+60000
            or _distance(origin, point) > 15):
        return None
    previous = _previous_arrival(db, vehicle, event['id'], start)
    if not previous:
        return None
    previous_id, encoded = previous
    previous = _summary(encoded)
    end = number(previous.get('end_time'), 1, 32503680000000)
    arrival = _telemetry(previous, 'end')
    if (previous.get('partial') is not False or end is None or not 0 < start-end <= MAX_PARKING_AGE_MS
            or arrival.get('state_time') != end or arrival.get('off') is not True
            or (arrival.get('speed') is not None and number(arrival.get('speed')) != 0)
            or number(arrival.get('odometer')) != odo):
        return None
    # A recorded intervening start without an ending defeats the parking estimate.
    if trip_start_between(db, vehicle, end, start):
        return None
    anchor = _point(previous.get('end_location'), trusted=True)
    if anchor is None:
        reference = previous.get('end_location_reference')
        if not isinstance(reference, dict) or number(reference.get('age_seconds'), 0, 300) is None:
            return None
        anchor = _point(reference.get('location'), trusted=True)
    if anchor is None or _distance(point, anchor) > RADIUS_M:
        return None
    return dict(source='parking_inferred', point=point, sample_time=stamp,
                previous_event_id=previous_id, previous_end_time=end,
                sampling_gap_seconds=round((start-stamp)/1000, 3),
                arrival_distance_m=round(_distance(point, anchor), 1))
