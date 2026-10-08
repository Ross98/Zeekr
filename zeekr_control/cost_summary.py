"""Actual recorded money from one personal-store snapshot, never estimates."""
import hashlib
import json
import time

from .usage_events import UsageEvents
from .usage_reports import period_window


def _money(value):
    return value if type(value) is int and value >= 0 else None


class CostsSummary:
    def __init__(self, store, database):
        self.store = store
        self.events = UsageEvents(database)

    def query(self, owner, vehicle, date, *, now=None):
        window = period_window('month', date)
        saved = self.store.read_many(owner, vehicle, ['charges', 'expenses'])
        active = {key: [dict(row['body'], id=row['id']) for row in value['records']
                        if not row['deleted']] for key, value in saved.items()}
        def in_month(row):
            value = row.get('date')
            return isinstance(value, str) and window['start_date'] <= value <= window['end_date']
        charges = [row for row in active['charges'] if in_month(row)]
        expenses = [row for row in active['expenses'] if in_month(row)]
        charge = [_money(row.get('actual_cents')) for row in charges]
        charge = [value for value in charge if value is not None]
        parking = sum(_money(row.get('parking_fee_cents')) or 0 for row in charges)
        daily = [_money(row.get('amount_cents')) for row in expenses]
        daily = [value for value in daily if value is not None]
        linked = {row['event'].get('id') for row in active['charges']
                  if isinstance(row.get('event'), dict)}
        events = self.events.between(vehicle, window['start'], window['end'])['events']
        pending = sum(row['kind'] == 'charge_end' and row['id'] not in linked for row in events)
        parking_bills = {(row['date'], row['parking_fee_cents']) for row in charges
                         if (_money(row.get('parking_fee_cents')) or 0) > 0}
        duplicates = [dict(id=row['id'], date=row['date'], title=row.get('title',''),
                           amount_cents=row.get('amount_cents')) for row in expenses
                      if '停车' in str(row.get('category','')) and
                      (row['date'], row.get('amount_cents')) in parking_bills]
        return dict(window=window, as_of=int(time.time()*1000) if now is None else now,
                    revisions={key:value['revision'] for key,value in saved.items()},
                    event_revision=hashlib.sha256(json.dumps(events,sort_keys=True).encode()).hexdigest(),
                    totals=dict(actual_cents=sum(charge)+parking+sum(daily) if charge or daily or parking else None,
                                charge_cents=sum(charge) if charge else None,
                                charge_parking_cents=parking if charges else None,
                                life_cents=sum(daily) if daily else None,
                                actual_charge_count=len(charge), life_count=len(daily),
                                unknown_charge_count=len(charges)-len(charge), unlinked_charge_count=pending),
                    duplicates=duplicates)
