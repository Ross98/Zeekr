"""Beijing month occupancy from ended events and observed, scoped snapshots."""
from datetime import datetime
import time

from .snapshot_archive import BEIJING
from .usage_events import UsageEvents
from .usage_reports import DAY, date_label, period_window
from .vehicle_state import decode


class UsageCalendar:
    def __init__(self,database,archive,clock=None):
        self.events=UsageEvents(database)
        self.archive=archive
        self.clock=clock or (lambda:int(time.time()*1000))

    def query(self,scope,vehicle,date,now=None):
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
        observations={}
        if upper>window['start']:
            for record,raw in self.archive.iter_records(scope,vehicle,window['start'],upper):
                day=by_date[date_label(record['observed_at'])]
                day['reads']+=1
                if day['first_read'] is None:day['first_read']=record['observed_at']
                day['last_read']=record['observed_at']
                stamp=record['state_time']
                if record['flags'] or stamp is None or stamp>now or record['change'] in ('repeat','regression'):
                    continue
                state=decode(raw)
                # Exact positive evidence only; unknown speed or charging does
                # not imply a parked vehicle. A later revision replaces state.
                parked=state['off'] is True and state['speed']==0 and state['charging'] is False
                observations[stamp]=(day['date'],parked)
        for stamp,(observed_date,parked) in observations.items():
            day=by_date[observed_date];day['effective_states']+=1
            if parked:
                day['parked_samples']+=1
                day['parking_first']=stamp if day['parking_first'] is None else min(day['parking_first'],stamp)
                day['parking_last']=stamp if day['parking_last'] is None else max(day['parking_last'],stamp)
        for day in days:
            if day['reads']:day['coverage']='observed' if day['effective_states'] else 'limited'
        return dict(window=window,as_of=now,weekday_offset=datetime.fromtimestamp(window['start']/1000,BEIJING).weekday(),
                    days=days,events=events,history_quality={'unreadable_or_undated':found['unreadable_or_undated']})
