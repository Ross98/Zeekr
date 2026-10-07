"""Read-only closed-calendar reports; ending events and bill-date payments."""
import time

from .snapshot_archive import BEIJING
from .tracks import day_bounds
from .usage_events import UsageEvents, number, total
from .usage_reports import aggregate, date_label, period_window


def report_window(period,date):
    if period == 'day':
        start,end=day_bounds(date)
        return dict(start=start,end=end,start_date=date,end_date=date,days=1)
    return period_window(period,date)


class PeriodicSummary:
    def __init__(self, database, archive, store):
        self.events = UsageEvents(database)
        self.archive, self.store = archive, store

    def query(self, scope, vehicle, owner, period, date, *, now=None, vehicle_time=None):
        now = int(time.time()*1000) if now is None else now
        window = report_window(period,date)
        if window['end'] > now:
            raise ValueError('报告期尚未结束。')
        found = self.events.between(vehicle,window['start'],window['end'])
        row = aggregate(found['events'],window,window['end']-1)
        trips = [e for e in row['events'] if e['kind']=='trip_end']
        charges = [e for e in row['events'] if e['kind']=='charge_end']
        observed, limited = set(), False
        try:
            for record in self.archive.iter_metadata(scope,vehicle,window['start'],window['end']):
                observed.add(date_label(record['observed_at']))
        except ValueError:
            limited = True
        saved = self.store.read(owner,vehicle,'charges')
        bills = [r['body'] for r in saved['records'] if not r['deleted']]
        selected = [b for b in bills if isinstance(b.get('date'),str)
                    and window['start_date']<=b['date']<=window['end_date']]
        payments = [number(b.get('actual_cents'),0,100000000) for b in selected]
        linked = {b['event']['id'] for b in bills if isinstance(b.get('event'),dict)
                  and isinstance(b['event'].get('id'),str)}
        metrics = {key:row['totals'][key] for key in ('trip_count','charge_count','distance_km',
                   'duration_seconds','trip_estimated_kwh','charge_estimated_kwh','estimated_kwh_per_100km')}
        metrics['charging_paid_cents'] = total(payments)
        quality = dict(observed_days=len(observed),elapsed_days=window['days'],archive_limited=limited,
            partial_event_count=sum(e['partial'] for e in row['events']),
            partial_trip_count=sum(e['partial'] for e in trips),
            missing_distance_count=sum(e['distance_km'] is None for e in trips),
            missing_duration_count=sum(e['duration_seconds'] is None for e in trips),
            missing_trip_energy_count=sum(e['estimated_kwh'] is None for e in trips),
            missing_charge_energy_count=sum(e['estimated_kwh'] is None for e in charges),
            unpriced_bill_count=sum(p is None for p in payments),
            pending_charge_bill_count=sum(e['id'] not in linked for e in charges),
            invalid_event_count=found['unreadable_or_undated'])
        return dict(schema_version=1,period=period,start_date=window['start_date'],end_date=window['end_date'],
                    generated_at=now,vehicle_updated_at=number(vehicle_time,1,now),
                    timezone='Asia/Shanghai',basis='ended_events_by_end_date',metrics=metrics,quality=quality)
