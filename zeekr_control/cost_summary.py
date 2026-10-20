"""Actual recorded money from one personal-store snapshot, never estimates."""
import hashlib
import json
import time

from .usage_events import UsageEvents
from .usage_reports import period_window


def _money(value):
    return value if type(value) is int and value >= 0 else None


def _record_rows(active, selected=None):
    rows = []
    for kind, collection in [('charge', 'charges'), ('life', 'expenses')]:
        for row in active[collection]:
            date = row.get('date')
            if not isinstance(date, str) or len(date) != 10 or (selected and date[:7] != selected):
                continue
            amount = _money(row.get('actual_cents' if kind == 'charge' else 'amount_cents'))
            parking = (_money(row.get('parking_fee_cents')) or 0) if kind == 'charge' else 0
            rows.append(dict(id=row['id'], date=date, kind=kind, source=row.get('source', 'unknown'),
                category='充电' if kind == 'charge' else row.get('category') or '未分类',
                title=(row.get('note') or '充电账单') if kind == 'charge' else row.get('title', ''),
                actual_cents=amount, parking_cents=parking,
                recorded_cents=None if amount is None and not parking else (amount or 0) + parking,
                updated_at=row.get('updated_at', 0)))
    return sorted(rows, key=lambda r: (r['date'], r['updated_at'], r['id']), reverse=True)


def _charts(active, selected, *, all_history=False, year=None):
    """Group recorded money only; absent months remain unknown, not free."""
    years = sorted({row['date'][:4] for collection in active.values() for row in collection
                    if isinstance(row.get('date'), str) and len(row['date']) == 10})
    chart_year = year or (years[-1] if years else selected[:4])
    year_number, month = map(int, selected.split('-'))
    end = year_number * 12 + month - 1
    months = ([chart_year + f'-{number:02d}' for number in range(1, 13)] if all_history else
              [f'{number // 12:04d}-{number % 12 + 1:02d}' for number in range(end - 5, end + 1)])
    grouped = {value: {} for value in months}
    if all_history:
        grouped['all'] = {}
        grouped.update({'annual:' + value: {} for value in years})

    def add(row, category, amount):
        date = row.get('date')
        key = date[:7] if isinstance(date, str) else ''
        if not isinstance(date, str) or len(date) != 10 or amount is None:
            return
        for target in ([key] if key in grouped else []) + (['all', 'annual:' + date[:4]] if all_history else []):
            group = grouped[target].setdefault(category, dict(category=category, amount_cents=0, count=0))
            group['amount_cents'] += amount
            group['count'] += 1

    for row in active['charges']:
        add(row, '充电', _money(row.get('actual_cents')))
        parking = _money(row.get('parking_fee_cents'))
        if parking:
            add(row, '充电停车费', parking)
    for row in active['expenses']:
        add(row, row.get('category') or '未分类', _money(row.get('amount_cents')))
    candidates = [row for row in _record_rows(active, None if all_history else selected)
                  if row['recorded_cents'] is not None]
    ordered = lambda groups: sorted(groups.values(), key=lambda r: (-r['amount_cents'], r['category']))
    return dict(categories=ordered(grouped['all' if all_history else selected]), years=years, year=chart_year,
        annual=[dict(year=value, actual_cents=sum(r['amount_cents'] for r in grouped['annual:' + value].values())
                     if grouped['annual:' + value] else None, categories=ordered(grouped['annual:' + value]))
                for value in years] if all_history else [],
        largest=max(candidates, key=lambda r: (r['recorded_cents'], r['date'], r['id'])) if candidates else None, months=[
        dict(month=value, actual_cents=sum(r['amount_cents'] for r in grouped[value].values())
             if grouped[value] else None, categories=ordered(grouped[value])) for value in months])


class CostsSummary:
    def __init__(self, store, database):
        self.store = store
        self.events = UsageEvents(database)

    def query(self, owner, vehicle, date, scope='month', page=0, category='', year=None, *, now=None):
        if scope not in ('month', 'all'):
            raise ValueError('费用范围无效。')
        try:
            page = int(page)
            if not 0 <= page <= 1000000:raise ValueError
        except (TypeError, ValueError):raise ValueError('费用页码无效。') from None
        if not isinstance(category, str) or len(category) > 24:raise ValueError('费用分类无效。')
        if year and (not isinstance(year, str) or len(year) != 4 or not year.isascii() or not year.isdigit()):
            raise ValueError('费用年份无效。')
        window = period_window('month', date)
        saved = self.store.read_many(owner, vehicle, ['charges', 'expenses'])
        active = {key: [dict(row['body'], id=row['id'], updated_at=row['updated_at']) for row in value['records']
                        if not row['deleted']] for key, value in saved.items()}
        def in_month(row):
            value = row.get('date')
            return isinstance(value, str) and len(value) == 10 and (scope == 'all' or window['start_date'] <= value <= window['end_date'])
        charges = [row for row in active['charges'] if in_month(row)]
        expenses = [row for row in active['expenses'] if in_month(row)]
        charge = [_money(row.get('actual_cents')) for row in charges]
        charge = [value for value in charge if value is not None]
        parking = sum(_money(row.get('parking_fee_cents')) or 0 for row in charges)
        daily = [_money(row.get('amount_cents')) for row in expenses]
        daily = [value for value in daily if value is not None]
        linked = {row['event'].get('id') for row in active['charges']
                  if isinstance(row.get('event'), dict)}
        events = self.events.between(vehicle, window['start'], window['end'])['events'] if scope == 'month' else []
        pending = sum(row['kind'] == 'charge_end' and row['id'] not in linked for row in events) if scope == 'month' else None
        parking_bills = {(row['date'], row['parking_fee_cents']) for row in charges
                         if (_money(row.get('parking_fee_cents')) or 0) > 0}
        duplicates = [dict(id=row['id'], date=row['date'], title=row.get('title',''),
                           amount_cents=row.get('amount_cents')) for row in expenses
                      if '停车' in str(row.get('category','')) and
                      (row['date'], row.get('amount_cents')) in parking_bills]
        charts = _charts(active, window['start_date'][:7], all_history=scope == 'all', year=year)
        records = None
        if scope == 'all':
            rows = _record_rows(active)
            window = dict(period='all', start_date=min((r['date'] for r in rows), default=None),
                          end_date=max((r['date'] for r in rows), default=None))
            filtered = [r for r in rows if not category or r['category'] == category or
                        (r['kind'] == 'charge' and category == '充电停车费' and r['parking_cents'] > 0)]
            page = min(page, max(0, (len(filtered) - 1) // 10))
            records = dict(rows=filtered[page * 10:page * 10 + 10], total=len(filtered), page=page,
                           count=len(rows), pages=max(1, (len(filtered) + 9) // 10))
        return dict(scope=scope, records=records, window=window, as_of=int(time.time()*1000) if now is None else now,
                    revisions={key:value['revision'] for key,value in saved.items()},
                    event_revision=hashlib.sha256(json.dumps(events,sort_keys=True).encode()).hexdigest(),
                    totals=dict(actual_cents=sum(charge)+parking+sum(daily) if charge or daily or parking else None,
                                charge_cents=sum(charge) if charge else None,
                                charge_parking_cents=parking if charges else None,
                                life_cents=sum(daily) if daily else None,
                                actual_charge_count=len(charge), life_count=len(daily),
                                unknown_charge_count=len(charges)-len(charge), unlinked_charge_count=pending),
                    duplicates=duplicates, charts=charts)
