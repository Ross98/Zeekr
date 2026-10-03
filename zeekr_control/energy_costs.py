"""Read-only weighted battery costs; unknown inventory never receives a price."""
from .usage_events import number, total
from .usage_reports import DAY, date_label


def estimate(events, books):
    result = {}
    capacity = stock = known = cents = None
    last_end = None
    for row in sorted(events, key=lambda e: (e['end_time'], e.get('start_time') or e['end_time'], e['id'])):
        cap = number(row.get('battery_capacity_kwh'), .001, 1000)
        if row['kind'] == 'parking' and cap is None:
            cap = capacity
        a = number(row.get('start_soc'), 0, 100)
        b = number(row.get('end_soc'), 0, 100)
        start, end = row.get('start_time'), row['end_time']
        valid = cap is not None and a is not None and b is not None and start is not None and start < end
        overlap = last_end is not None and (start is None or start < last_end)
        energy = number(row.get('estimated_kwh'), 0, 1000)
        if row['kind'] == 'parking' and valid:
            energy = max(0, (a-b)*cap/100) if a >= b else None
        charge = row['kind'] == 'charge_end'
        delta = (b-a if charge else a-b)*cap/100 if valid else None
        valid = valid and not overlap and energy is not None and delta >= 0 and abs(delta-energy) < .02
        cost = dict(energy_kwh=energy, known_kwh=0, unknown_kwh=energy,
                    estimated_cents=None, reference_cents_per_kwh=None, status='unknown',
                    data_partial=bool(row.get('partial')), overlap=overlap)
        if not valid:
            capacity = cap
            stock = b*cap/100 if b is not None and cap is not None else None
            known = cents = 0
        else:
            initial = a*cap/100
            if stock is None or capacity != cap:
                stock, known, cents = initial, 0, 0
            elif initial < stock:
                ratio = initial/stock if stock else 0
                known *= ratio; cents *= ratio; stock = initial
            elif initial > stock:
                stock = initial  # unobserved gain is unknown-priced energy
            capacity = cap
            if charge:
                book = books.get(row['id'], {})
                fee = number(book.get('actual_cents'), 0, 100000000)
                meter = number(book.get('metered_kwh'), .000001, 10000)
                priced = not row.get('partial') and fee is not None and meter is not None and meter >= energy and energy > 0
                stock += energy
                if priced:
                    known += energy; cents += fee
                cost.update(known_kwh=energy if priced else 0, unknown_kwh=0 if priced else energy,
                            estimated_cents=fee if priced else None,
                            reference_cents_per_kwh=fee/energy if priced else None,
                            status='priced' if priced else 'unknown')
            else:
                ratio = min(1, energy/stock) if stock else 0
                used_known, used_cents = known*ratio, cents*ratio
                cost.update(known_kwh=round(used_known, 6), unknown_kwh=round(max(0, energy-used_known), 6),
                            estimated_cents=round(used_cents, 6) if used_known > 0 or energy == 0 else None,
                            reference_cents_per_kwh=cents/known if known > 0 else None,
                            status='priced' if abs(energy-used_known)<.000001 else 'partial' if used_known > 0 else 'unknown')
                stock = max(0, stock-energy); known -= used_known; cents -= used_cents
        result[row['id']] = cost
        last_end = max(last_end or end, end)
    return result


def summarize(rows):
    costs = [r['energy_cost'] for r in rows]
    return dict(estimated_cents=total(c['estimated_cents'] for c in costs),
                energy_kwh=total(c['energy_kwh'] for c in costs),
                known_kwh=total(c['known_kwh'] for c in costs),
                unknown_kwh=total(c['unknown_kwh'] for c in costs),
                samples=len(costs), missing_energy_count=sum(c['energy_kwh'] is None for c in costs),
                partial_count=sum(c['data_partial'] or c['status'] != 'priced' for c in costs),
                parking_samples=sum(r['kind']=='parking' for r in rows))


def attach(events_source, vehicle, window, now, events, books, sessions):
    upper = min(now+1, max([window['end']] + [e['end_time']+1 for e in events]))
    limited = False
    try:
        history = events_source.between(vehicle, max(0, window['start']-180*DAY), upper)
    except ValueError as failure:
        if not any(word in str(failure) for word in ('过大', '过多')):
            raise
        history = dict(events=events, unreadable_or_undated=0); limited = True
    rows = [dict(e) for e in history['events'] if e['end_time'] <= now]
    parking = [dict(id='parking:'+s['id'], kind='parking', start_time=s['start_time'], end_time=s['end_time'],
                    start_soc=s['start_soc'], end_soc=s['end_soc'], estimated_kwh=None,
                    battery_capacity_kwh=None, partial=False, sample_count=s['sample_count'],
                    end_date=date_label(s['end_time'])) for s in sessions if s['eligible']]
    costs = estimate(rows+parking, {} if limited else books)
    for row in events+parking:
        if row['id'] in costs:
            row['energy_cost'] = costs[row['id']]
    consumption = [e for e in events+parking if e['kind'] != 'charge_end' and 'energy_cost' in e]
    return consumption, dict(history_days=180, history_limited=limited,
                             unreadable_or_undated=history['unreadable_or_undated'])
