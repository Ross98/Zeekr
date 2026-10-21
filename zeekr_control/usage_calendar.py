"""Beijing month occupancy from ended events and observed, scoped snapshots."""
from datetime import datetime
import time

from .snapshot_archive import BEIJING
from .usage_events import UsageEvents, total
from .usage_reports import DAY, date_label, period_window
from .parking_analytics import ParkingAnalytics
from .energy_costs import attach, summarize
from .analysis_work import TimeMap


class UsageCalendar:
    def __init__(self,database,archive,clock=None,store=None):
        self.events=UsageEvents(database)
        self.store=store
        self.archive=archive
        self.clock=clock or (lambda:int(time.time()*1000))

    def query(self,scope,vehicle,date,now=None,owner=None):
        now=self.clock() if now is None else now
        window=period_window('month',date)
        days=[dict(date=date_label(window['start']+i*DAY),trip_count=0,charge_count=0,
                   partial_count=0,reads=0,effective_states=0,parked_samples=0,
                   first_read=None,last_read=None,parking_first=None,parking_last=None,
                   coverage='future' if window['start']+i*DAY>now else 'missing')
              for i in range(window['days'])]
        by_date={row['date']:row for row in days}
        found=self.events.between(vehicle,window['start'],window['end'],overlap=True)
        events=[]
        for event in found['events']:
            if event['end_time']>now:continue
            start,end=event['start_time'],event['end_time']
            # An ended interval occupies [start,end); an unknown start is only
            # evidence on its end date. Never apportion whole-event metrics.
            first,last=(start,end-1) if start is not None and start<end else (end,end)
            first_date,last_date=date_label(first),date_label(last)
            events.append(dict(event,first_date=first_date,last_date=last_date,cross_midnight=first_date!=last_date))
            for day in days:
                if first_date<=day['date']<=last_date:
                    day['trip_count' if event['kind']=='trip_end' else 'charge_count']+=1
                    day['partial_count']+=int(event['partial'])
        upper=min(window['end'],now+1)
        def observe(sample):
            record,state=sample['record'],sample['state']
            day=by_date.get(date_label(record['observed_at']))
            if day is not None:
                day['reads']+=1
                if day['first_read'] is None:day['first_read']=record['observed_at']
                day['last_read']=record['observed_at']
            stamp=record['state_time']
            if day is not None and not record['flags'] and stamp is not None and stamp<=now and record['change'] not in ('repeat','regression'):
                parked=state['off'] is True and state['speed']==0 and state['charging'] is False
                observations.set(stamp,day['date'],parked)
        with TimeMap() as observations:
            if upper>window['start']:
                analyzed=ParkingAnalytics(self.archive,self.events.path,store=self.store,owner=owner or scope).query(
                    scope,vehicle,date_label(window['start']),date_label(window['end']-1),context_days=1,observe=observe,now=now)
                parking=analyzed['sessions'];parking_events=analyzed.get('events',[])
            else:parking=[];parking_events=[]
            for observed_date,count,parked,first,last in observations.daily():
                day=by_date[observed_date]
                day.update(effective_states=count,parked_samples=parked,parking_first=first,parking_last=last)
        for day in days:
            if day['reads']:day['coverage']='observed' if day['effective_states'] else 'limited'
        totals,revision=self.enrich(owner or scope,vehicle,window,days,events,now,parking,parking_events)
        return dict(window=window,as_of=now,weekday_offset=datetime.fromtimestamp(window['start']/1000,BEIJING).weekday(),
                    days=days,events=events,totals=totals,ledger_revision=revision,
                    history_quality={'unreadable_or_undated':found['unreadable_or_undated']})

    def enrich(self,owner,vehicle,window,days,events,now,parking,parking_events=()):
        saved=self.store.read(owner,vehicle,'charges') if self.store else dict(records=[],revision=0)
        entries=[dict(r['body'],id=r['id']) for r in saved['records'] if not r['deleted']]
        booked={r['event']['id']:r for r in entries if isinstance(r.get('event'),dict)}
        for event in events:
            event['end_date']=date_label(event['end_time'])
            if event['kind']=='charge_end':
                bill=booked.get(event['id'])
                event['bill']={k:v for k,v in bill.items() if k!='event'} if bill else None
                event['needs_bill']=bill is None or bill['actual_cents'] is None
        trips=[e for e in events if e['kind']=='trip_end']
        parking_places=[]
        if self.store and trips:
            from .trip_places import TripPlaces
            from .trip_place_names import TripPlaceNames
            from .commute_tags import CommuteTags
            names=TripPlaceNames(self.store)
            stats=names.apply(owner,vehicle,TripPlaces(self.events.path).query(vehicle,trips,names.regions(owner,vehicle)),CommuteTags(self.store,self.events.path).rule(owner,vehicle))
            from .daily_timeline import DailyTimeline
            interpreter=DailyTimeline(self.events.path,self.archive,self.store)
            corrections=self.store.read(owner,vehicle,'place_corrections')
            corrections['_regions']=names.regions(owner,vehicle)
            places={p['id']:p for p in stats['places']}
            for event in trips:
                for side in ('start','end'):
                    interpreted=interpreter._interpret(owner,vehicle,places.get(event.pop(side+'_place',None)),event['id'],side,corrections)
                    event[side+'_label']=interpreted['label'] if interpreted['key'] else ('起点未知' if side=='start' else '终点未知')
                    event[side+'_place_key']=interpreted['key']
        if self.store:
            for event in parking_events:
                if event['place_source']=='unknown' or not window['start']<=event['end_time']<window['end']:continue
                parking_places.append(dict(key=event['place_statistics_key'] or event['place_key'],
                                           label=event['place_label'],date=date_label(event['end_time']),
                                           record_id=event['place_record_id'],duration_seconds=event['duration_seconds'],
                                           confidence=event['place_confidence'],evidence=event['place_evidence']))
        consumption,quality=attach(self.events,vehicle,window,now,events,booked,parking)
        for day in days:
            day['energy_cost']=summarize([e for e in consumption if date_label(e['end_time'])==day['date']])
            ended=[e for e in events if e['end_date']==day['date']]
            driving=[e for e in ended if e['kind']=='trip_end']
            bills=[r for r in entries if r['date']==day['date']]
            day.update(distance_km=total(e['distance_km'] for e in driving),
                       distance_samples=sum(e['distance_km'] is not None for e in driving),
                       duration_seconds=total(e['duration_seconds'] for e in driving),
                       duration_samples=sum(e['duration_seconds'] is not None for e in driving),
                       partial_duration_samples=sum(e['duration_seconds'] is not None and e['partial'] for e in driving),
                       ended_trip_count=len(driving),
                       actual_cents=total(r['actual_cents'] for r in bills),
                       actual_count=sum(r['actual_cents'] is not None for r in bills),
                       unpriced_count=sum(r['actual_cents'] is None for r in bills),
                       pending_count=sum(e.get('needs_bill',False) for e in ended))
        ended=[e for e in events if window['start']<=e['end_time']<window['end']]
        driving=[e for e in ended if e['kind']=='trip_end']
        return dict(parking_places=parking_places,distance_km=total(e['distance_km'] for e in driving),
                    distance_samples=sum(e['distance_km'] is not None for e in driving),
                    duration_seconds=total(e['duration_seconds'] for e in driving),
                    duration_samples=sum(e['duration_seconds'] is not None for e in driving),
                    partial_duration_samples=sum(e['duration_seconds'] is not None and e['partial'] for e in driving),
                    trip_count=len(driving),charge_count=sum(e['kind']=='charge_end' for e in ended),
                    usage_days=sum(d['trip_count']>0 for d in days),
                    energy_cost=summarize([e for e in consumption if window['start']<=e['end_time']<window['end']]),
                    energy_cost_quality=quality,
                    parking_costs=[e for e in consumption if e['kind']=='parking'],
                    actual_cents=total(d['actual_cents'] for d in days),
                    actual_count=sum(d['actual_count'] for d in days),
                    unpriced_count=sum(d['unpriced_count'] for d in days),
                    pending_count=sum(e.get('needs_bill',False) for e in ended)),saved['revision']
