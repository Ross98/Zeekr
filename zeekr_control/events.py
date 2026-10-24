"""Privacy-safe vehicle event summaries for local Web views."""
import base64
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
from .charging_details import history_details
from .archive_reader import _private
from .trip_visibility import visible_clause
from .start_evidence import from_summary as start_evidence
from .usage_events import project, MAX_SUMMARY_BYTES
from .tracks import day_bounds


ALLOWED_KINDS = {'trip_end', 'charge_end'}
PUBLIC_FIELDS = ('start_time', 'end_time', 'duration_seconds', 'distance_km',
                 'start_soc', 'end_soc', 'soc_delta', 'partial', 'battery_capacity_kwh')


def public_event(event_id, kind, summary):
    observed = project(event_id, kind, summary) or {}
    values={key:observed.get(key) for key in PUBLIC_FIELDS}
    values['partial']=observed.get('partial',True)
    return dict(id=event_id, kind=kind, **values,
                start_evidence=start_evidence(summary, kind), estimated_kwh=observed.get('estimated_kwh'))


def _cursor(created, event_id):
    return base64.urlsafe_b64encode(json.dumps([created, event_id], separators=(',', ':')).encode()).decode().rstrip('=')


def _decode(value):
    try:
        raw = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
        created, event_id = json.loads(raw)
        if (type(created) not in (int,float) or not math.isfinite(created)
                or not -(2**63)<=created<=2**63-1 or not isinstance(event_id,str)):
            raise ValueError
        return created, event_id
    except Exception as exc:
        raise ValueError('事件游标无效。') from exc


class EventStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def _connect(self):
        if not self.path.exists() and not self.path.is_symlink():
            yield None
            return
        _private(self.path.parent,directory=True)
        _private(self.path)
        db=sqlite3.connect(self.path.absolute().as_uri()+'?mode=ro',uri=True,timeout=5)
        try:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            yield db
        finally:
            db.close()

    def query(self, vehicle, date, kind, cursor=None, limit=20, end_date=None):
        if not vehicle or kind not in ALLOWED_KINDS or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('事件查询参数无效。')
        lower,_=day_bounds(date)
        last,upper=day_bounds(end_date or date)
        if last < lower:
            raise ValueError('结束日期不能早于开始日期。')
        boundary = _decode(cursor) if cursor else None
        with self._connect() as db:
            if db is None:
                return {'events': [], 'next_cursor': None, 'date': date, 'kind': kind}
            query = ('SELECT id,CASE WHEN length(CAST(summary AS BLOB))<=? THEN summary END,created '
                     'FROM monitor_events WHERE vehicle=? AND kind=? AND '+visible_clause(db))
            parameters = [MAX_SUMMARY_BYTES, vehicle, kind]
            if boundary:
                query += ' AND (created,id)<(?,?)'
                parameters.extend(boundary)
            rows = db.execute(query + ' ORDER BY created DESC,id DESC', parameters)
            selected = []
            for event_id, encoded, created in rows:
                try:
                    summary = json.loads(encoded)
                except (TypeError, ValueError, RecursionError):
                    continue
                if not isinstance(summary, dict):
                    continue
                end_time = summary.get('end_time')
                if type(end_time) not in (int, float) or not lower <= end_time < upper:
                    continue
                selected.append((event_id, created, summary))
                if len(selected) > limit:
                    break
        page = selected[:limit]
        events = [public_event(event_id, kind, summary) for event_id, _, summary in page]
        if kind == 'charge_end':
            for event, (_, _, summary) in zip(events, page):
                event['charging_details'] = history_details(summary.get('report_v2'))
        next_cursor = _cursor(page[-1][1], page[-1][0]) if len(selected) > limit and page else None
        return {'events': events, 'next_cursor': next_cursor, 'date': date, 'kind': kind}

    def latest(self, vehicle):
        if not vehicle:
            return {'trip_end': None, 'charge_end': None}
        result = {'trip_end': None, 'charge_end': None}
        with self._connect() as db:
            if db is None:return result
            # Stop at the first valid event of each kind. Never materialize the
            # full private history to return these two small public summaries.
            for kind in result:
                rows = db.execute('SELECT id,CASE WHEN length(CAST(summary AS BLOB))<=? THEN summary END '
                                  'FROM monitor_events WHERE vehicle=? AND kind=? AND '
                                  + visible_clause(db) + ' ORDER BY created DESC,id DESC',
                                  (MAX_SUMMARY_BYTES, vehicle, kind))
                for event_id, encoded in rows:
                    try:
                        summary = json.loads(encoded)
                    except (TypeError, ValueError, RecursionError):
                        continue
                    if not isinstance(summary, dict):
                        continue
                    if project(event_id,kind,summary) is None:
                        continue
                    result[kind] = public_event(event_id, kind, summary)
                    break
        return result
