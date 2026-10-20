"""Scoped charging review from saved events, bills and historical place names."""
import json
import time

from .charging_analytics import _mode
from .energy_costs import estimate
from .usage_events import UsageEvents, number, total
from .usage_reports import DAY, date_label, period_window
from .trip_places import TripPlaces
from .trip_place_names import TripPlaceNames
from .commute_tags import CommuteTags


class ChargingReview:
    def __init__(self, database, store):
        self.events = UsageEvents(database)
        self.database = database
        self.store = store

    @staticmethod
    def _summary(rows):
        known = [r for r in rows if r['bill'] and r['bill']['actual_cents'] is not None]
        return dict(charge_count=len(rows), partial_count=sum(r['partial'] for r in rows),
                    estimated_kwh=total(r['estimated_kwh'] for r in rows),
                    energy_samples=sum(r['estimated_kwh'] is not None for r in rows),
                    actual_cents=total(r['bill']['actual_cents'] for r in known),
                    known_count=len(known), pending_count=len(rows)-len(known))

    def _places(self, owner, vehicle, records):
        names = TripPlaceNames(self.store)
        stats = TripPlaces(self.database).query(vehicle, records, names.regions(owner, vehicle))
        stats = names.apply(owner, vehicle, stats, CommuteTags(self.store, self.database).rule(owner, vehicle))
        places = {p['id']:p for p in stats['places']}
        for record in records:
            candidates = [places.get(record.pop(side+'_place', None)) for side in ('start','end')]
            place = next((p for p in candidates if p and p['name_source'] != 'reference'), None)
            record['place_label'] = place['label'] if place else '地点未知'
            record['place_source'] = place['name_source'] if place else 'unknown'
            record['place_reference'] = bool(record.pop('start_place_evidence', None) or record.pop('end_place_evidence', None))
            record.pop('end_place_evidence', None)

    def query(self, owner, vehicle, date, now=None):
        now = int(time.time()*1000) if now is None else now
        window = period_window('month', date)
        previous = period_window('month', window['previous_date'])
        upper = max(window['start'], min(window['end'], now+1))
        previous_upper = previous['end'] if upper == window['end'] else min(previous['end'], previous['start']+max(0, upper-window['start']))
        # Event summaries only: no decompression of the full snapshot archive.
        history = self.events.between(vehicle, max(0, window['start']-180*DAY), upper if upper>window['start'] else window['start']+1)
        all_events = [e for e in history['events'] if e['end_time'] <= now]
        saved = self.store.read(owner, vehicle, 'charges')
        books = {r['body']['event']['id']:dict(r['body'], id=r['id']) for r in saved['records']
                 if not r['deleted'] and isinstance(r['body'].get('event'), dict)}
        records = []
        earlier = []
        for event in all_events:
            if event['kind'] != 'charge_end':continue
            current = window['start'] <= event['end_time'] < upper
            prior = previous['start'] <= event['end_time'] < previous_upper
            if not current and not prior:continue
            bill = books.get(event['id'])
            public_bill = {k:bill.get(k) for k in ('id','date','actual_cents','metered_kwh','service_fee_cents','parking_fee_cents')} if bill else None
            row = dict(event, bill=public_bill, mode='unknown')
            (records if current else earlier).append(row)
        # Confirm both saved mode endpoints; conflicting codes remain unknown.
        if records:
            with self.events.connect() as db:
                for row in records:
                    encoded = db.execute('SELECT summary FROM monitor_events WHERE vehicle=? AND id=?', (vehicle,row['id'])).fetchone()
                    try:raw = json.loads(encoded[0]) if encoded else {}
                    except (ValueError,TypeError):raw = {}
                    report = raw.get('report_v2') if isinstance(raw,dict) else None
                    row['mode'] = _mode(report) if isinstance(report,dict) else 'unknown'
                    override = books.get(row['id'], {}).get('charge_mode_override')
                    row['mode_source'] = 'saved'
                    if override in ('ac','dc'):
                        row['mode'] = override
                        row['mode_source'] = 'manual'
            self._places(owner, vehicle, records)
        summary = self._summary(records)
        previous_summary = self._summary(earlier)
        pairs = [r for r in records if r['bill'] and r['bill']['actual_cents'] is not None
                 and number(r['bill']['metered_kwh'], .000001, 10000) is not None]
        metered = total(r['bill']['metered_kwh'] for r in pairs)
        paired_cents = total(r['bill']['actual_cents'] for r in pairs)
        groups = []
        for mode in ('ac','dc','unknown'):
            rows = [r for r in records if r['mode'] == mode]
            info = self._summary(rows)
            groups.append(dict(mode=mode, **info, share_percent=100*info['actual_cents']/summary['actual_cents']
                if info['actual_cents'] is not None and summary['actual_cents'] is not None and summary['actual_cents']>0 else None))
        current_cost, prior_cost = summary['actual_cents'], previous_summary['actual_cents']
        costs = estimate(all_events, books)
        trips = [e for e in all_events if e['kind']=='trip_end' and window['start']<=e['end_time']<upper]
        # Unchanged SOC on a driven trip cannot establish zero consumption.
        # Keep it out of both the priced numerator and mileage denominator.
        matched = [e for e in trips if number(e['distance_km'],.000001) is not None and not e['partial']
                   and number(e['estimated_kwh'], .000001) is not None
                   and costs[e['id']]['status']=='priced' and not costs[e['id']]['overlap']
                   and costs[e['id']]['estimated_cents'] is not None]
        distance = total(e['distance_km'] for e in matched)
        driving_cents = total(costs[e['id']]['estimated_cents'] for e in matched)
        return dict(window=window, as_of=now, records=records, summary=summary, groups=groups,
            ledger_revision=saved['revision'], history_quality=dict(unreadable_or_undated=history['unreadable_or_undated'],history_days=180),
            analysis=dict(unit_price_cents_per_kwh=paired_cents/metered if metered and paired_cents is not None else None,
                          metered_kwh=metered, matched_cents=paired_cents, metered_samples=len(pairs)),
            comparison=dict(previous_actual_cents=prior_cost, previous_known_count=previous_summary['known_count'],
                            previous_pending_count=previous_summary['pending_count'], current_end_date=date_label(upper-1) if upper>window['start'] else None,
                            previous_start_date=previous['start_date'], previous_end_date=date_label(previous_upper-1) if previous_upper>previous['start'] else None,
                            change_cents=current_cost-prior_cost if current_cost is not None and prior_cost is not None else None,
                            change_percent=100*(current_cost-prior_cost)/prior_cost if current_cost is not None and prior_cost is not None and prior_cost>0 else None),
            driving=dict(cents_per_100km=driving_cents/distance*100 if distance and driving_cents is not None else None,
                         matched_distance_km=distance, estimated_cents=driving_cents, included_trip_count=len(matched),
                         total_trip_count=len(trips), excluded_trip_count=len(trips)-len(matched),
                         matched_energy_kwh=total(e['estimated_kwh'] for e in matched),
                         loss_unknown=any(costs[e['id']]['loss_unknown'] for e in matched)))
