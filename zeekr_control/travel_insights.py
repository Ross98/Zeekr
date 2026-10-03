"""On-demand local route comparisons and weekly reviews; no telemetry requests."""
from .charge_ledger import ChargeLedger
from .commute_tags import CommuteTags
from .trip_place_names import TripPlaceNames
from .trip_places import TripPlaces
from .trip_tags import comparison
from .usage_events import UsageEvents, total
from .usage_reports import period_window


class TravelInsights:
    def __init__(self,store,database):
        self.store=store;self.events=UsageEvents(database);self.places=TripPlaces(database)
        self.names=TripPlaceNames(store);self.commute=CommuteTags(store,database)
        self.ledger=ChargeLedger(store,database)

    def _read(self,owner,vehicle,date,period):
        window=period_window(period,date)
        source=self.events.between(vehicle,window['start'],window['end'])
        trips=[r for r in source['events'] if r['kind']=='trip_end']
        stats=self.names.apply(owner,vehicle,self.places.query(vehicle,trips,self.names.regions(owner,vehicle)),self.commute.rule(owner,vehicle))
        labels={p['id']:p['label'] for p in stats['places']}
        for row in trips:
            row.update(start_label=labels.get(row['start_place'],'未知'),end_label=labels.get(row['end_place'],'未知'))
        return window,source,trips,stats,labels

    def routes(self,owner,vehicle,date):
        window,source,trips,stats,labels=self._read(owner,vehicle,date,'month')
        routes=[];grouped={}
        for row in trips:grouped.setdefault((row['start_place'],row['end_place']),[]).append(row)
        for direction in stats['routes']:
            rows=grouped[(direction['start_place'],direction['end_place'])]
            summary=comparison('',rows);summary.pop('tag')
            routes.append(dict(summary,**{k:direction[k] for k in ('start_place','end_place')},
                start_label=labels[direction['start_place']],end_label=labels[direction['end_place']],
                events=sorted(rows,key=lambda r:(r['end_time'],r['id']),reverse=True)))
        return dict(window=window,routes=routes,trip_count=len(trips),
                    unknown_route_count=sum(not r['start_place'] or not r['end_place'] for r in trips),
                    unreadable_or_undated=source['unreadable_or_undated'])

    def review(self,owner,vehicle,date):
        window,source,trips,stats,labels=self._read(owner,vehicle,date,'week')
        # A week can straddle two ledger months. Deduplicate entries, then use
        # bill date for expenses and event end time for the pending charge list.
        books=[self.ledger.query(owner,vehicle,d) for d in sorted({window['start_date'][:7]+'-01',window['end_date'][:7]+'-01'})]
        entries={r['id']:r for book in books for r in book['entries']
                 if window['start_date']<=r['date']<=window['end_date']}
        booked={e['id'] for book in books for e in book['events'] if e['recorded']}
        pending=[r for r in source['events'] if r['kind']=='charge_end' and r['id'] not in booked]
        actual=[r['actual_cents'] for r in entries.values() if r['actual_cents'] is not None]
        parking=[r['parking_fee_cents'] for r in entries.values()]
        expenses=[r['body'] for r in self.store.read(owner,vehicle,'expenses')['records']
                  if not r['deleted'] and window['start_date']<=r['body']['date']<=window['end_date']]
        costs=actual+[p for p in parking if p!=0]+[r['amount_cents'] for r in expenses]
        return dict(window=window,trip_count=len(trips),partial_trip_count=sum(r['partial'] for r in trips),
                    distance_km=total(r['distance_km'] for r in trips),distance_samples=sum(r['distance_km'] is not None for r in trips),
                    places=[dict(id=p['id'],label=p['label'],departures=p['departures'],arrivals=p['arrivals']) for p in stats['places']],
                    unknown_departures=stats['unknown_departures'],unknown_arrivals=stats['unknown_arrivals'],
                    costs=dict(actual_cents=sum(costs) if costs else None,charge_cents=sum(actual) if actual else None,
                               parking_cents=sum(parking) if entries else None,life_cents=sum(r['amount_cents'] for r in expenses) if expenses else None,
                               bill_count=len(entries),life_count=len(expenses),unknown_charge_count=sum(r['actual_cents'] is None for r in entries.values())),
                    pending=pending,pending_count=len(pending),unreadable_or_undated=source['unreadable_or_undated'])
