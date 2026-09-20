"""Read-only local trip selection and public summaries; never expose locations."""
import json
import math
import re

from .events import EventStore, PUBLIC_FIELDS, _decode
from .tracks import TrackStore, day_bounds, valid_timestamp
from .trip_visibility import visible_clause, revision


VALID_ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')


def _number(value):
    try:
        return value if type(value) in (int, float) and math.isfinite(value) else None
    except OverflowError:
        return None


def _object(value):
    return value if isinstance(value, dict) else {}


def _summary(value, identity, status):
    result = {key: _number(value.get(key)) for key in PUBLIC_FIELDS if key != 'partial'}
    result.update(id=identity, kind='trip_end' if status == 'ended' else 'trip', status=status,
                  partial=value.get('partial') is not False)
    return result


class TripStore:
    def __init__(self, path):
        self.tracks = TrackStore(path, readonly=True)
        self.events = EventStore(path)

    def _rows(self, table, query, parameters=(), visible=False):
        if not self.tracks.path.exists():
            return []
        with self.tracks.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                return []
            return db.execute(query + (' AND '+visible_clause(db) if visible else ''), parameters).fetchall()

    def vehicles(self):
        """Find even event-only archives without inventing a default vehicle."""
        vehicles = set()
        for table in ('observations', 'monitor_events', 'monitor_state'):
            vehicles.update(row[0] for row in self._rows(table, 'SELECT DISTINCT vehicle FROM ' + table)
                            if isinstance(row[0], str) and row[0])
        return vehicles

    def active(self, vehicle):
        if not vehicle:
            return None
        rows = self._rows('monitor_state', 'SELECT payload FROM monitor_state WHERE vehicle=?', (vehicle,))
        if not rows:
            return None
        try:
            state = _object(json.loads(rows[0][0]))
        except (ValueError, TypeError):
            return None
        trip = _object(state.get('trip'))
        if not trip:
            return None
        start = _object(trip.get('start'))
        stop = _object(trip.get('stop'))
        end = stop or _object(state.get('last'))
        lower, upper = start.get('time'), end.get('time')
        if not valid_timestamp(lower) or not valid_timestamp(upper) or upper < lower:
            return None
        start_km, end_km = _number(start.get('km')), _number(end.get('km'))
        start_soc, end_soc = _number(start.get('soc')), _number(end.get('soc'))
        distance = end_km - start_km if start_km is not None and end_km is not None else None
        negative_distance = distance is not None and distance < 0
        value = {'start_time': lower, 'end_time': upper, 'duration_seconds': (upper - lower) / 1000,
                 'distance_km': round(distance, 3) if distance is not None and not negative_distance else None,
                 'start_soc': start_soc, 'end_soc': end_soc,
                 'soc_delta': round(end_soc - start_soc, 3) if start_soc is not None and end_soc is not None else None,
                 'partial': trip.get('partial') is not False or negative_distance,
                 'battery_capacity_kwh': _object(trip.get('profile')).get('battery_capacity_kwh')}
        return _summary(value, 'current', 'waiting' if stop else 'driving')

    def query(self, vehicle, date, cursor=None):
        lower, upper = day_bounds(date)
        if cursor is not None:
            _decode(cursor)
        result = {'events': [], 'next_cursor': None, 'active': None, 'date': date, 'revision': 0}
        if not vehicle:
            return result
        if self.tracks.path.exists():
            with self.tracks.connect() as db:
                result['revision'] = revision(db, vehicle)
        if self._rows('monitor_events', 'SELECT 1 FROM monitor_events LIMIT 1'):
            page = self.events.query(vehicle, date, 'trip_end', cursor=cursor)
            result.update(events=[_summary(event, event['id'], 'ended') for event in page['events']],
                          next_cursor=page['next_cursor'])
        active = self.active(vehicle)
        if active and active['start_time'] < upper and active['end_time'] >= lower:
            result['active'] = active
        return result

    def bounds(self, vehicle, selection, date):
        lower, upper = day_bounds(date)
        if not vehicle or not isinstance(selection, str) or not VALID_ID.fullmatch(selection):
            raise ValueError('请选择有效的本地行程。')
        if selection == 'current':
            value = self.active(vehicle)
            if not value or value['start_time'] >= upper or value['end_time'] < lower:
                raise ValueError('当前日期没有进行中的本地行程。')
        else:
            rows = self._rows('monitor_events',
                              'SELECT summary FROM monitor_events WHERE vehicle=? AND id=? AND kind=?',
                              (vehicle, selection, 'trip_end'), visible=True)
            if not rows:
                raise ValueError('行程不存在或不属于当前车辆。')
            try:
                value = _object(json.loads(rows[0][0]))
            except (ValueError, TypeError):
                raise ValueError('行程记录无法读取。') from None
        start, end = value.get('start_time'), value.get('end_time')
        if not valid_timestamp(start) or not valid_timestamp(end) or end < start:
            raise ValueError('行程时间范围无效。')
        return start, end
