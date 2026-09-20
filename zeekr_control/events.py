"""Privacy-safe vehicle event summaries for local Web views."""
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from .charging_details import history_details


ALLOWED_KINDS = {'trip_end', 'charge_end'}
PUBLIC_FIELDS = ('start_time', 'end_time', 'duration_seconds', 'distance_km',
                 'start_soc', 'end_soc', 'soc_delta', 'partial', 'battery_capacity_kwh')


def _cursor(created, event_id):
    return base64.urlsafe_b64encode(json.dumps([created, event_id], separators=(',', ':')).encode()).decode().rstrip('=')


def _decode(value):
    try:
        raw = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
        created, event_id = json.loads(raw)
        if type(created) is not int or not isinstance(event_id, str):
            raise ValueError
        return created, event_id
    except Exception as exc:
        raise ValueError('事件游标无效。') from exc


class EventStore:
    def __init__(self, path):
        self.path = Path(path)

    def query(self, vehicle, date, kind, cursor=None, limit=20):
        if not vehicle or kind not in ALLOWED_KINDS or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('事件查询参数无效。')
        try:
            day = datetime.strptime(date, '%Y-%m-%d').replace(tzinfo=timezone(timedelta(hours=8)))
        except ValueError as exc:
            raise ValueError('日期格式无效。') from exc
        lower, upper = int(day.timestamp() * 1000), int((day + timedelta(days=1)).timestamp() * 1000)
        boundary = _decode(cursor) if cursor else None
        if not self.path.exists():
            return {'events': [], 'next_cursor': None, 'date': date, 'kind': kind}
        db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            query = 'SELECT id,summary,created FROM monitor_events WHERE vehicle=? AND kind=?'
            parameters = [vehicle, kind]
            if boundary:
                query += ' AND (created,id)<(?,?)'
                parameters.extend(boundary)
            rows = db.execute(query + ' ORDER BY created DESC,id DESC', parameters)
            selected = []
            for event_id, encoded, created in rows:
                try:
                    summary = json.loads(encoded)
                except (TypeError, ValueError):
                    continue
                if not isinstance(summary, dict):
                    continue
                end_time = summary.get('end_time')
                if type(end_time) not in (int, float) or not lower <= end_time < upper:
                    continue
                selected.append((event_id, created, summary))
                if len(selected) > limit:
                    break
        finally:
            db.close()
        page = selected[:limit]
        events = [dict({'id': event_id, 'kind': kind},
                       **{key: summary.get(key) for key in PUBLIC_FIELDS})
                  for event_id, _, summary in page]
        if kind == 'charge_end':
            for event, (_, _, summary) in zip(events, page):
                event['charging_details'] = history_details(summary.get('report_v2'))
        next_cursor = _cursor(page[-1][1], page[-1][0]) if len(selected) > limit and page else None
        return {'events': events, 'next_cursor': next_cursor, 'date': date, 'kind': kind}

    def latest(self, vehicle):
        if not vehicle or not self.path.exists():
            return {'trip_end': None, 'charge_end': None}
        result = {'trip_end': None, 'charge_end': None}
        db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            # Stop at the first valid event of each kind. Never materialize the
            # full private history to return these two small public summaries.
            for kind in result:
                rows = db.execute('''SELECT id,summary FROM monitor_events
                                     WHERE vehicle=? AND kind=? ORDER BY created DESC,id DESC''',
                                  (vehicle, kind))
                for event_id, encoded in rows:
                    try:
                        summary = json.loads(encoded)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(summary, dict):
                        continue
                    result[kind] = dict({'id': event_id, 'kind': kind},
                                        **{key: summary.get(key) for key in PUBLIC_FIELDS})
                    break
        finally:
            db.close()
        return result
