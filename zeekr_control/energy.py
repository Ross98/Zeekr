"""Read-only attainment for the selected vehicle's latest completed trip."""
import json
import math
import sqlite3
from pathlib import Path

from .summary import updated_at


def _number(value, low, high):
    return (type(value) in (int, float) and low <= value <= high
            and math.isfinite(value))


def read_attainment(database_path, vehicle, profile):
    path = Path(database_path)
    if not vehicle or not path.exists():
        return {'status': 'no_trip'}
    try:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
        try:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_events'").fetchone():
                return {'status': 'no_trip'}
            row = db.execute("SELECT summary FROM monitor_events WHERE vehicle=? AND kind='trip_end' "
                             "ORDER BY created DESC,rowid DESC LIMIT 1", (vehicle,)).fetchone()
        finally:
            db.close()
        if not row:
            return {'status': 'no_trip'}
        trip = json.loads(row[0])
    except (sqlite3.Error, ValueError, OSError, TypeError):
        return {'status': 'unavailable'}
    if not isinstance(trip, dict):
        return {'status': 'invalid'}
    result = {'status': 'invalid'}
    start_time, end_time = trip.get('start_time'), trip.get('end_time')
    if not (_number(start_time, 1, 32503680000000) and _number(end_time, 1, 32503680000000)
            and end_time > start_time):
        return result
    result.update(start_at=updated_at(start_time), end_at=updated_at(end_time))
    if trip.get('partial') is not False:
        return dict(result, status='incomplete')
    start, end = trip.get('start_soc'), trip.get('end_soc')
    distance, delta = trip.get('distance_km'), trip.get('soc_delta')
    if not (_number(start, 0, 100) and _number(end, 0, 100)
            and _number(distance, 0, 1e9) and _number(delta, -100, 100)):
        return result
    used = start - end
    if used <= 0:
        return dict(result, status='no_consumption')
    if abs(delta + used) > .001:
        return result
    profile = profile or {}
    rated = profile.get('range_km')
    standard = profile.get('range_standard')
    if not (_number(rated, 0, 3000) and rated > 0 and standard in ('CLTC', 'WLTP', 'NEDC', 'EPA')):
        return dict(result, status='no_rating')
    reference = rated * used / 100
    ratio = distance / reference * 100
    if not math.isfinite(ratio):
        return result
    return dict(result, status='available', distance_km=distance, start_soc=start, end_soc=end,
                used_soc=used, reference_km=reference, ratio=ratio, standard=standard)
