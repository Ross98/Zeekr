"""Trustworthy endpoint observations, bounded to three minutes and 128 rows."""
import json
import math


def endpoint(db, vehicle, lower, upper, near_start):
    direction = 'ASC' if near_start else 'DESC'
    rows = db.execute('SELECT state_time,location FROM observations WHERE vehicle=? '
                              'AND state_time>=? AND state_time<=? ORDER BY state_time '+direction+',observed_time DESC,id DESC LIMIT 128',
                              (vehicle, lower, upper)).fetchall()
    for timestamp, encoded in rows:
        try:
            point = json.loads(encoded)
            lat, lon = point.get('latitude'), point.get('longitude')
            if (point.get('trusted') is True and point.get('plottable') is True
                    and point.get('coordinate_system') == 'WGS84（社区解释）'
                    and type(lat) in (int,float) and type(lon) in (int,float)
                    and math.isfinite(lat) and math.isfinite(lon)
                    and -90 <= lat <= 90 and -180 <= lon <= 180 and (lat != 0 or lon != 0)):
                return timestamp, (lat, lon)
        except (ValueError, TypeError, AttributeError):
            continue
    return None
