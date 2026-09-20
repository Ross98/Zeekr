"""Calendar week/month reports from ended events and private archive metadata."""
from datetime import datetime, timedelta
import time

from .snapshot_archive import BEIJING
from .tracks import day_bounds
from .usage_events import UsageEvents, total

DAY = 86400000


def date_label(stamp):
    return datetime.fromtimestamp(stamp/1000, BEIJING).strftime('%Y-%m-%d')


def period_window(period, date):
    lower, _ = day_bounds(date)
    day = datetime.fromtimestamp(lower/1000, BEIJING)
    if period == 'week':
        start = day-timedelta(days=day.weekday())
        end, previous = start+timedelta(days=7), start-timedelta(days=7)
    elif period == 'month':
        start = day.replace(day=1)
        end = (start.replace(day=28)+timedelta(days=4)).replace(day=1)
        previous = (start-timedelta(days=1)).replace(day=1)
    else:
        raise ValueError('请选择周报或月报。')
    return {'period': period, 'start': int(start.timestamp()*1000), 'end': int(end.timestamp()*1000),
            'start_date': start.strftime('%Y-%m-%d'), 'end_date': (end-timedelta(days=1)).strftime('%Y-%m-%d'),
            'previous_date': previous.strftime('%Y-%m-%d'), 'next_date': end.strftime('%Y-%m-%d'),
            'days': (end-start).days}


def aggregate(events, window, as_of):
    events = [row for row in events if window['start'] <= row['end_time'] < min(window['end'], as_of+1)]
    trips = [row for row in events if row['kind'] == 'trip_end']
    charges = [row for row in events if row['kind'] == 'charge_end']
    complete = [row for row in trips if not row['partial']]
    partial = [row for row in trips if row['partial']]
    energy = [row for row in trips if row['estimated_kwh'] is not None]
    efficiency = [row for row in energy if row['distance_km'] is not None and row['distance_km'] >= 10
                  and row['soc_delta'] is not None and -row['soc_delta'] >= 3]
    charge_energy = [row for row in charges if row['estimated_kwh'] is not None]
    efficiency_distance = total(row['distance_km'] for row in efficiency)
    efficiency_energy = total(row['estimated_kwh'] for row in efficiency)
    totals = {'trip_count':len(trips), 'complete_trip_count':len(complete), 'partial_trip_count':len(partial),
        'charge_count':len(charges), 'complete_charge_count':sum(not row['partial'] for row in charges),
        'partial_charge_count':sum(row['partial'] for row in charges),
        'distance_km':total(row['distance_km'] for row in trips),
        'complete_distance_km':total(row['distance_km'] for row in complete),
        'partial_distance_km':total(row['distance_km'] for row in partial),
        'duration_seconds':total(row['duration_seconds'] for row in trips),
        'complete_duration_seconds':total(row['duration_seconds'] for row in complete),
        'partial_duration_seconds':total(row['duration_seconds'] for row in partial),
        'trip_estimated_kwh':total(row['estimated_kwh'] for row in energy),
        'charge_estimated_kwh':total(row['estimated_kwh'] for row in charge_energy),
        'estimated_kwh_per_100km':round(efficiency_energy/efficiency_distance*100,6) if efficiency_distance else None}
    samples = {'distance':sum(row['distance_km'] is not None for row in trips),
        'partial_distance':sum(row['distance_km'] is not None for row in partial),
        'duration':sum(row['duration_seconds'] is not None for row in trips),
        'partial_duration':sum(row['duration_seconds'] is not None for row in partial),
        'trip_energy':len(energy), 'charge_energy':len(charge_energy), 'efficiency':len(efficiency)}
    days = [{'date':date_label(window['start']+i*DAY), 'trip_count':0, 'charge_count':0,
             'distance_km':None,'partial_trip_count':0,'coverage':'future' if window['start']+i*DAY > as_of else 'missing'}
            for i in range(window['days'])]
    hours = [0]*24
    for row in events:
        day = days[int((row['end_time']-window['start'])//DAY)]
        day['trip_count' if row['kind']=='trip_end' else 'charge_count'] += 1
        if row['kind']=='trip_end':
            day['partial_trip_count'] += int(row['partial'])
            if row['distance_km'] is not None:
                day['distance_km'] = round((day['distance_km'] or 0)+row['distance_km'],6)
            if row['start_time'] is not None:
                hours[datetime.fromtimestamp(row['start_time']/1000,BEIJING).hour] += 1
    status = 'closed' if as_of >= window['end'] else 'upcoming' if as_of < window['start'] else 'ongoing'
    return {'window':window,'status':status,'totals':totals,'samples':samples,'days':days,
            'departure_hours':hours,'events':events}


class UsageReports:
    def __init__(self, database, archive, clock=None):
        self.events = UsageEvents(database)
        self.archive = archive
        self.clock = clock or (lambda: int(time.time()*1000))

    def _coverage(self, scope, vehicle, result, as_of):
        window = result['window']
        counts = {'reads':0,'new_states':0,'revisions':0,'repeats':0,'invalid_or_stale':0,
                  'days_with_reads':0,'first_read':None,'last_read':None}
        dates, seen = set(), set()
        upper = min(window['end'],as_of+1)
        if upper > window['start']:
            for record in self.archive.iter_metadata(scope,vehicle,window['start'],upper):
                counts['reads'] += 1
                stamp = record['observed_at']
                dates.add(date_label(stamp))
                if counts['first_read'] is None:counts['first_read'] = stamp
                counts['last_read'] = stamp
                counts['repeats'] += int(record['change']=='repeat')
                counts['revisions'] += int(record['change']=='revision')
                if record['flags'] or record['change']=='regression':
                    counts['invalid_or_stale'] += 1
                elif record['change'] in ('first','new') and record['state_time'] not in seen:
                    seen.add(record['state_time']);counts['new_states'] += 1
        counts['days_with_reads'] = len(dates)
        for day in result['days']:
            if day['date'] in dates:day['coverage'] = 'observed'
        result['coverage'] = counts

    def query(self, scope, vehicle, period, date, now=None):
        now = self.clock() if now is None else now
        current_window = period_window(period,date)
        previous_window = period_window(period,current_window['previous_date'])
        found = self.events.between(vehicle,previous_window['start'],current_window['end'])
        current = aggregate(found['events'],current_window,now)
        previous = aggregate(found['events'],previous_window,now)
        for result in (current,previous):self._coverage(scope,vehicle,result,now)
        comparable = current['status']=='closed' and previous['status']=='closed'
        metrics = {}
        for key in ('distance_km','trip_count','charge_count','duration_seconds','trip_estimated_kwh'):
            a,b = previous['totals'][key],current['totals'][key]
            reason = ('period_open' if not comparable else 'missing_samples' if a is None or b is None
                      else 'zero_base' if a==0 else None)
            metrics[key] = {'previous':a,'current':b,'difference':round(b-a,6) if a is not None and b is not None else None,
                            'percent':round((b-a)/a*100,2) if reason is None else None,'reason':reason}
        return {'period':period,'as_of':now,'current':current,'previous':previous,
                'comparison':{'comparable':comparable,'metrics':metrics},
                'history_quality':{'unreadable_or_undated':found['unreadable_or_undated']}}
