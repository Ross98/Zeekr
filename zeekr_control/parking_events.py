"""Find stationary intervals outside saved trips; preserve source records."""
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from itertools import chain

from .snapshot_archive import BEIJING
from .vehicle_state import numeric
from .geocoding import is_trusted_location
from .tracks import valid_timestamp
from .analysis_work import ResultRows, SampleRows, SampleStore, TimeMap


MAX_GAP_MS = 600000
GPS_DRIFT_METERS = 15
LABELS = {
    'gap': '停车期间有超过 10 分钟的数据缺口',
    'charging': '充电阶段边界或观测不足，无法分离充电与耗电',
    'movement': '停车期间有移动或里程变化证据',
    'invalid': '停车期间有异常时间或无效观测',
    'soc': '电量观测缺失或阶段内 SOC 变化无法可靠分离',
    'boundary': '缺少可靠的停车起止边界',
    'observations': '停车起止附近缺少有效观测',
    'unknown': '停车期间充电状态不明',
    'location': '位置观测不足，停车状态待确认',
}


def time_advances(record, previous):
    """Vehicle time, not equal telemetry values or a repeat label, proves a new observation."""
    if previous is None:
        return False
    current, old = record.get('state_time'), previous.get('state_time')
    return (type(current) in (int, float) and type(old) in (int, float)
            and current > old)


def observation_time(sample):
    record=sample['record']
    stamp=record.get('state_time')
    return stamp if valid_timestamp(stamp) else record['observed_at']


def fresh(sample):
    record=sample['record']
    return not record.get('flags') and record.get('change')!='regression' and valid_timestamp(record.get('state_time'))


def observation_quality(reads, samples, start, end):
    with TimeMap() as times:
        stamps=(row[0] for row in samples.with_condition('r.fresh').query('r.stamp')) if isinstance(samples,SampleRows) else (
            row['record']['state_time'] for row in samples if fresh(row))
        for stamp in stamps:times.add(stamp)
        count, first, last = times.db.execute('SELECT COUNT(*),MIN(stamp),MAX(stamp) FROM times').fetchone()
        times.add(start);times.add(end)
        previous=None;supported=unknown=maximum=gap_count=0;gaps=[]
        for (stamp,) in times.db.execute('SELECT stamp FROM times ORDER BY stamp'):
            if previous is not None:
                delta=stamp-previous;maximum=max(maximum,delta)
                if delta>MAX_GAP_MS:
                    gap_count+=1;unknown+=delta/1000
                    if len(gaps)<50:gaps.append(dict(start_time=previous,end_time=stamp,duration_seconds=delta/1000))
                else:supported+=delta
            previous=stamp
        times.db.execute('DELETE FROM times')
        read_count=repeats=invalid=0;last_read=None
        points=(reads.query('r.observed,r.stamp,r.fresh,r.change') if isinstance(reads,SampleRows) else
                ((row['record']['observed_at'],row['record'].get('state_time'),fresh(row),row['record'].get('change')) for row in reads))
        for observed,stamp,is_fresh,change in points:
            read_count+=1;invalid+=not is_fresh
            last_read=observed if last_read is None else max(last_read,observed)
            if valid_timestamp(stamp):repeats+=not times.add(stamp) and change!='revision'
        return dict(read_count=read_count,fresh_samples=count,repeat_reads=repeats,
                    invalid_reads=invalid,first_vehicle_time=first,last_vehicle_time=last,
                    last_read_time=last_read,max_gap_seconds=maximum/1000,
                    supported_seconds=supported/1000,unknown_seconds=unknown,
                    gap_count=gap_count,gaps_limited=gap_count>50),gaps


def location_key(sample):
    location = sample.get('location') or {}
    if location.get('valid') and location.get('latitude') is not None and location.get('longitude') is not None:
        return (location['latitude'], location['longitude'], location.get('coordinate_system'))
    return None


def stationary_support(first, second):
    """Small coordinate changes need corroboration from both vehicle observations."""
    a, b = first['state'], second['state']
    return (a.get('km') is not None and a.get('km') == b.get('km')
            and all((state.get('off') is True or state.get('gear') == 'P')
                    and state.get('off') is not False
                    and state.get('gear') not in ('R', 'D')
                    and not (state.get('speed') is not None and state['speed'] > 0)
                    for state in (a, b)))


def same_position(first, second):
    """Compare against a fixed anchor, never a chain of nearby moving points."""
    a, b = location_key(first), location_key(second)
    if a is None or b is None or a[2] != b[2]:
        return False
    if a == b:
        return True
    if not stationary_support(first, second):
        return False
    lat1, lat2 = radians(a[0]), radians(b[0])
    distance = 2 * 6371000 * asin(min(1, sqrt(
        sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin(radians(b[1]-a[1])/2)**2)))
    return distance <= GPS_DRIFT_METERS


def charging_energy(charges, samples, start, end, boundary_socs):
    """Separate SOC gain during known charge phases from noncharging SOC loss.

    Exact endpoint observations are required; charge SOC gain is not input kWh.
    Missing/overlapping phases never imply zero consumption.
    """
    phases = []
    for charge in charges:
        a, b = charge.get('start_time'), charge.get('end_time')
        if b is None or b <= start or (a is not None and a >= end):
            continue
        phases.append({'start_time': a, 'end_time': b,
                       'duration_seconds': (b-a)/1000 if a is not None and b >= a else None,
                       'soc_gain': None,'boundary_complete':charge.get('partial') is not True})
    phases.sort(key=lambda row: row['start_time'] if row['start_time'] is not None else start)
    boundaries={phase[key] for phase in phases for key in ('start_time','end_time')}
    exact={}
    if boundaries:
        points=(samples.with_condition('r.fresh').query('r.stamp,r.soc') if isinstance(samples,SampleRows) else
                ((row['record']['state_time'],row['state'].get('soc')) for row in samples if fresh(row)))
        exact={stamp:soc for stamp,soc in points if stamp in boundaries}
    phase_known = True
    consumption_known = all(value is not None for value in boundary_socs)
    gain, previous = 0, start
    for phase in phases:
        a, b = phase['start_time'], phase['end_time']
        if (not phase['boundary_complete'] or a is None or a < previous or b > end or b <= a
                or exact.get(a) is None or exact.get(b) is None or exact[b] < exact[a]):
            phase_known = False
        else:
            phase['soc_gain'] = round(exact[b]-exact[a], 6)
            gain += phase['soc_gain']
        previous = b
    charging_times=((row[0] for row in samples.with_condition('r.charging=1').query('r.instant')) if isinstance(samples,SampleRows) else
                    (observation_time(row) for row in samples if row['state'].get('charging') is True))
    uncovered_charge = any(not any(phase['start_time'] is not None and phase['start_time']<=stamp<=phase['end_time']
                                  for phase in phases) for stamp in charging_times)
    if uncovered_charge:
        phase_known = False
        phases.append({'start_time': None, 'end_time': None, 'duration_seconds': None, 'soc_gain': None})
    sample_points=(samples.query('r.instant,r.soc') if isinstance(samples,SampleRows) else
                   ((observation_time(row),row['state'].get('soc')) for row in samples))
    points = chain(((start,boundary_socs[0]),),sample_points,
                   ((end,boundary_socs[1]),))
    consumption = 0
    previous_point=next(points)
    for b,y in points:
        a,x=previous_point;previous_point=b,y
        if x is None or y is None:
            consumption_known = False
            continue
        inside = any(phase['start_time'] is not None and phase['end_time'] is not None
                     and phase['start_time'] <= a < b <= phase['end_time'] for phase in phases)
        if inside:
            if y < x:
                consumption_known = False
        elif y > x:
            consumption_known = False
        else:
            consumption += x-y
    return phases, round(gain, 6) if phase_known else None, consumption if phase_known and consumption_known else None


def _run_event(before, after, within, reads, start, end, open_end, clipped, charges, capacity):
    first = last = first_fresh = last_fresh = position = None
    public_position = trusted_position = None
    position_count = p_gear_samples = 0
    stationary = True
    movement = unknown = invalid = False
    first_km = previous_stamp = None
    for row in within.projected():
        if first is None:first=row
        last=row
        record,state=row['record'],row['state']
        if location_key(row) is not None:
            position_count+=1
            if position is None:position=row
            elif not same_position(position,row):stationary=False
            if public_position is None and row['location'].get('coordinate_system')=='WGS84（社区解释）':
                public_position=row['location']
        if fresh(row):
            if first_fresh is None:first_fresh=row
            last_fresh=row;p_gear_samples+=state.get('gear')=='P'
            if (trusted_position is None and is_trusted_location(row.get('location')) and
                    row['location']['coordinate_system']=='WGS84（社区解释）'):
                trusted_position=row['location']
        km=state.get('km')
        if km is not None:
            if first_km is None:first_km=km
            elif km!=first_km:movement=True
        movement|=state.get('gear') in ('R','D') or state.get('speed') is not None and state['speed']>0
        unknown|=state.get('charging') is None
        stamp=record.get('state_time')
        invalid|=bool(record.get('flags')) or record.get('change')=='regression' or not valid_timestamp(stamp)
        invalid|=previous_stamp is not None and stamp is not None and stamp<previous_stamp
        previous_stamp=stamp
    if first is None:return None
    stationary=stationary and position_count>=2 and not movement
    quality,gaps=observation_quality(reads,within,start,end)
    reasons=set()
    if movement:reasons.add('movement')
    if clipped or before is None or after is None or before.get('partial') or after.get('partial'):reasons.add('boundary')
    if first_fresh is None or observation_time(first_fresh)-start>MAX_GAP_MS or end-observation_time(last_fresh)>MAX_GAP_MS:
        reasons.add('observations')
    if quality['gap_count']:reasons.add('gap')
    if not stationary:reasons.add('location')
    if unknown:reasons.add('unknown')
    if invalid:reasons.add('invalid')
    boundary_socs=[before.get('end_soc') if before and start==before['end_time'] else first['state'].get('soc'),
                   after.get('start_soc') if after and end==after['start_time'] else last['state'].get('soc')]
    phases,gain,consumption=charging_energy(charges,within,start,end,boundary_socs)
    if gain is None:reasons.add('charging')
    if consumption is None:reasons.add('soc')
    drop=round(consumption,6) if not reasons else None
    duration=(end-start)/1000
    category=('multi_day' if duration>=86400 else 'overnight' if
              datetime.fromtimestamp(start/1000,BEIJING).date()!=datetime.fromtimestamp(end/1000,BEIJING).date() else 'same_day')
    return {'id':(before['id'] if before else 'range')+':'+(after['id'] if after else 'open')+':'+str(start),
            'start_time':start,'end_time':end,'duration_seconds':duration,'category':category,
            'start_trip_id':before['id'] if before else None,'end_trip_id':after['id'] if after else None,
            'start_soc':boundary_socs[0],'end_soc':boundary_socs[1],
            'charging_phases':phases,'charged_soc_gain':gain,'soc_drop':drop,
            'estimated_kwh':round(drop*capacity/100,4) if drop is not None and capacity else None,
            'status':'comparable' if not reasons else 'uncertain','open':open_end,
            'parking_status':'parked' if stationary else 'candidate','p_gear_samples':p_gear_samples,
            'reasons':sorted(reasons),'reason_labels':[LABELS[key] for key in sorted(reasons)],
            'sample_count':quality['fresh_samples'],'gap_count':quality['gap_count'],
            'observation_quality':quality,'observation_gaps':gaps,
            '_position':public_position,'_location':trusted_position}


def _stream_events(trips, charges, store, lower, upper, capacity):
    trips=sorted((row for row in trips if row.get('kind')=='trip_end' and
                  isinstance(row.get('start_time'),(int,float)) and isinstance(row.get('end_time'),(int,float))),
                 key=lambda row:(row['start_time'],row['end_time']))
    first=store.canonical().first()
    cursor=observation_time(first) if first else lower
    windows=[];previous_trip=None
    for trip in trips:
        if trip['start_time']>cursor:windows.append((cursor,trip['start_time'],previous_trip,trip))
        cursor=max(cursor,trip['end_time']) if previous_trip else trip['end_time']
        previous_trip=trip
    latest=store.db.execute('SELECT MAX(r.instant) FROM canonical c JOIN samples r ON r.id=c.source_id WHERE r.fresh').fetchone()[0]
    latest=cursor if latest is None else latest
    if first and cursor<latest:windows.append((cursor,latest,previous_trip,None))
    read_latest=store.db.execute('SELECT MAX(observed) FROM samples').fetchone()[0]
    events=ResultRows()
    for left,right,before,after in windows:
        if right<=lower or left>=upper:continue
        where='r.instant>=? AND r.instant<=?';args=(left,right)
        if after:
            where+=" AND NOT (r.instant=? AND (COALESCE(r.gear IN ('R','D'),0) OR COALESCE(r.speed,0)>0))"
            args+=(right,)
        selected=store.canonical(where,args)
        run_first=run_last=anchor=last_sample=None
        run_index=0
        def finish(has_next):
            if run_first is None:return
            start=left if run_index==0 else observation_time(run_first[1])
            end=observation_time(run_last[1]) if has_next else right
            open_end=after is None
            if open_end:end=min(end,observation_time(run_last[1]))
            if end<=start or end<=lower or start>=upper:return
            within=selected.between_ids(run_first[0],run_last[0])
            read_end=read_latest if open_end and read_latest is not None else end
            reads=store.raw('(r.observed BETWEEN ? AND ?) OR (r.instant BETWEEN ? AND ? AND r.observed>? AND r.observed<=?)',
                            (start,read_end,start,end,end,end+MAX_GAP_MS))
            event=_run_event(before,after,within,reads,start,end,open_end,run_index>0 or has_next,charges,capacity)
            if event is not None:events.append(event)
        for identity,row in selected.projected(indexed=True):
            current=location_key(row)
            split=(current is not None and anchor is not None and (not same_position(anchor,row) or
                   (location_key(anchor)!=current and not stationary_support(last_sample,row))))
            if split:
                finish(True);run_index+=1;run_first=run_last=None
            if run_first is None:run_first=(identity,row)
            run_last=(identity,row);last_sample=row
            if current is not None and (anchor is None or run_first[0]==identity):anchor=row
        finish(False)
    events.sort(key=lambda row:row['start_time'],reverse=True)
    return {'events':events,'parking_count':sum(row['parking_status']=='parked' for row in events),
            'comparable_count':sum(row['status']=='comparable' for row in events),
            'uncertain_count':sum(row['status']=='uncertain' for row in events),'calculation_version':6}


def build_events(trips, charges, samples, lower, upper, capacity=None):
    """V6 semantics over a one-pass source; scratch storage is disposed on exit."""
    capacity=numeric(capacity,.001,1000)
    if isinstance(samples,SampleStore):
        return _stream_events(trips,charges,samples,lower,upper,capacity)
    with SampleStore(samples) as store:
        return _stream_events(trips,charges,store,lower,upper,capacity)
