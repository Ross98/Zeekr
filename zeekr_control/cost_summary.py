"""Actual recorded money from one personal-store snapshot, never estimates."""
import hashlib
import json
import time

from .usage_events import UsageEvents
from .usage_reports import period_window


def _money(value):
    return value if type(value) is int and value >= 0 else None


def _charts(active, selected):
    """Group recorded money only; absent months remain unknown, not free."""
    year, month = map(int, selected.split('-'))
    end = year * 12 + month - 1
    months = [f'{number // 12:04d}-{number % 12 + 1:02d}'
              for number in range(end - 5, end + 1)]
    grouped = {value: {} for value in months}

    def add(row, category, amount):
        date = row.get('date')
        key = date[:7] if isinstance(date, str) else ''
        if key not in grouped or amount is None:
            return
        group = grouped[key].setdefault(category, dict(category=category, amount_cents=0, count=0))
        group['amount_cents'] += amount
        group['count'] += 1

    for row in active['charges']:
        add(row, '充电', _money(row.get('actual_cents')))
        parking = _money(row.get('parking_fee_cents'))
        if parking:
            add(row, '充电停车费', parking)
    for row in active['expenses']:
        add(row, row.get('category') or '未分类', _money(row.get('amount_cents')))
    candidates = []
    for kind, collection in [('charge', 'charges'), ('life', 'expenses')]:
        for row in active[collection]:
            if not isinstance(row.get('date'), str) or row['date'][:7] != selected:
                continue
            amount = _money(row.get('actual_cents' if kind == 'charge' else 'amount_cents'))
            parking = (_money(row.get('parking_fee_cents')) or 0) if kind == 'charge' else 0
            if amount is None and not parking:
                continue
            candidates.append(dict(id=row['id'], date=row['date'], kind=kind,
                category='充电' if kind == 'charge' else row.get('category') or '未分类',
                title=(row.get('note') or '充电账单') if kind == 'charge' else row.get('title', ''),
                actual_cents=amount, parking_cents=parking, recorded_cents=(amount or 0) + parking))
    ordered = lambda groups: sorted(groups.values(), key=lambda r: (-r['amount_cents'], r['category']))
    return dict(categories=ordered(grouped[selected]),
        largest=max(candidates, key=lambda r: (r['recorded_cents'], r['date'], r['id'])) if candidates else None, months=[
        dict(month=value, actual_cents=sum(r['amount_cents'] for r in grouped[value].values())
             if grouped[value] else None, categories=ordered(grouped[value])) for value in months])


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
                    duplicates=duplicates, charts=_charts(active, window['start_date'][:7]))
