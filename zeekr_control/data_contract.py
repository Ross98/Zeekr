"""Shared public data semantics. No credentials, I/O or implicit cloud queries."""
from datetime import datetime
import time

from .snapshot_archive import BEIJING

PERSONAL_COLLECTIONS = ('charges', 'expenses', 'place_names', 'place_corrections', 'charging_places')


def date_at(now):
    return datetime.fromtimestamp(now / 1000, BEIJING).strftime('%Y-%m-%d')


def recorded_by(row, now):
    date = row.get('date')
    return isinstance(date, str) and len(date) == 10 and date <= date_at(now)


def charge_mode(report):
    report = report if isinstance(report, dict) else {}
    modes = [part.get('charging_mode') for part in (report.get('start'), report.get('end'))
             if isinstance(part, dict) and part.get('charging_mode') is not None]
    return modes[0] if modes and all(mode == modes[0] and mode in ('ac', 'dc') for mode in modes) else 'unknown'


def response_body(status, value):
    """Add metadata without moving existing fields or inventing a read cutoff."""
    body = dict(value)
    meta = dict(body.get('meta') or {})
    meta.update(schema_version=1, generated_at=int(time.time()*1000), timezone='Asia/Shanghai',
                units=dict(timestamp='unix_milliseconds', duration='seconds', money='integer_cents',
                           distance='km', energy='kWh'))
    context = body.get('context', body.get('insights_context'))
    if context is not None:meta['context'] = context
    if 'as_of' in body:meta['as_of'] = body['as_of']
    revisions = {key:body[key] for key in ('revision','revisions','snapshot_revision','trip_records_revision',
                 'charge_records_revision','personal_records_revision','ledger_revision') if key in body}
    if revisions:meta['revisions'] = revisions
    body['meta'] = meta
    if status >= 400:
        body.setdefault('code', {400:'invalid_request',401:'login_required',403:'forbidden',404:'not_found',
            409:'data_changed',429:'rate_limited',500:'internal_error',502:'gateway_error',503:'unavailable'}.get(status,'request_failed'))
        body.setdefault('retryable', status in (429,500,502,503))
    return body
