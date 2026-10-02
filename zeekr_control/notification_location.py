"""Bounded historical references for notification text, never raw track repairs."""
import json
import math

from .geocoding import is_trusted_location

MAX_REFERENCE_AGE_MS = 300000


def select_location(db, vehicle, location, event_time):
    """Return the endpoint or the most recent usable point before that endpoint."""
    if is_trusted_location(location):
        return location, None
    if type(event_time) not in (int, float) or not math.isfinite(event_time) or event_time <= 0:
        return None, None
    rows = db.execute('''SELECT state_time, observed_time, location FROM observations
        WHERE vehicle=? AND state_time>=? AND state_time<=?
        ORDER BY state_time DESC, observed_time DESC, id DESC''',
        (vehicle, event_time - MAX_REFERENCE_AGE_MS, event_time))
    for state_time, observed_time, encoded in rows:
        try:
            candidate = json.loads(encoded)
        except (TypeError, ValueError):
            continue
        if is_trusted_location(candidate):
            reference = {'state_time': state_time, 'observed_time': observed_time,
                         'age_seconds': (event_time - state_time) / 1000,
                         'location': candidate}
            return candidate, reference
    return None, None


def reference_suffix(reference):
    if not isinstance(reference, dict):
        return ''
    age = reference.get('age_seconds')
    if type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 300:
        return ''
    elapsed = ('%g秒' % math.ceil(age)) if age < 60 else ('%g分钟' % round(age / 60, 1))
    return '（参考位置，%s前可信定位）' % elapsed
