"""Bounded historical charging positions, independent of current vehicle state."""
import json

from .analysis_cancel import check_cancelled
from .commute_tags import _distance
from .parking_origin import _point, _summary, _telemetry
from .usage_events import MAX_SUMMARY_BYTES, number
from .trip_visibility import visible_clause
from .movement_barriers import trip_movement_between

RADIUS_M = 75
MAX_SAMPLES = 2048
MAX_TELEMETRY_BYTES = 65536


def coordinates(point):
    return dict(latitude=point[0], longitude=point[1]) if point else None


def _fresh(stamp, observed):
    return (number(stamp,1,32503680000000) is not None
            and number(observed,1,32503680000000) is not None and -30000<=observed-stamp<=180000)


def _stationary_between(db, vehicle, event):
    """Infer only when both adjoining trips and advancing stopped telemetry agree."""
    start,end=event.get('start_time'),event['end_time']
    if start is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='report_observations'").fetchone():return None
    trips=[]
    # Apply the resource limit to relevant candidates. Later trips cannot make
    # an unchanged historical charging location lose its supporting evidence.
    rows=db.execute("SELECT id,summary FROM monitor_events WHERE vehicle=? AND kind='trip_end' AND "+visible_clause(db)+
        ' AND CASE WHEN length(CAST(summary AS BLOB))<=? THEN '
        "CASE WHEN json_valid(summary) THEN json_type(summary,'$.start_time') IN ('integer','real') "
        "AND json_type(summary,'$.end_time') IN ('integer','real') "
        "AND json_extract(summary,'$.start_time')<=? AND json_extract(summary,'$.end_time')>=? "
        'ELSE 0 END ELSE 0 END ORDER BY created DESC LIMIT 1025',
        (vehicle,MAX_SUMMARY_BYTES,end+900000,start-900000))
    for index,(identity,encoded) in enumerate(rows):
        check_cancelled()
        if index>=1024:return None
        raw=_summary(encoded);a=number(raw.get('start_time'),1,32503680000000);b=number(raw.get('end_time'),1,32503680000000)
        if a is not None and b is not None and a<b and raw.get('partial') is False:
            trips.append(dict(id=identity,start_time=a,end_time=b,start_location=raw.get('start_location'),end_location=raw.get('end_location')))
    arrivals=[r for r in trips if start-900000<=r['end_time']<=start]
    departures=[r for r in trips if end<=r['start_time']<=end+900000]
    if not arrivals or not departures:return None
    previous=max(arrivals,key=lambda r:r['end_time']);following=min(departures,key=lambda r:r['start_time'])
    a,b=previous['end_time'],following['start_time']
    left=_point(previous.get('end_location'),trusted=True);right=_point(following.get('start_location'),trusted=True)
    if not left or not right or _distance(left,right)>RADIUS_M:return None
    # Hidden/partial trips cannot support a point, but still contradict parking.
    if trip_movement_between(db, vehicle, a, b, exclude_event_ids=(previous['id'],following['id']),
                             unknown_lower_inclusive=True):return None
    rows=db.execute('SELECT state_time,observed_at,CASE WHEN length(CAST(normalized_payload AS BLOB))<=? THEN normalized_payload END FROM report_observations WHERE vehicle=? AND state_time>=? AND state_time<=? ORDER BY state_time LIMIT ?', (MAX_TELEMETRY_BYTES,vehicle,a,b,MAX_SAMPLES+1))
    stamps=[];odometer=None
    for index,(stamp,observed,encoded) in enumerate(rows):
        if index>=MAX_SAMPLES:return None
        check_cancelled();raw=_summary(encoded);mileage=number(raw.get('odometer'))
        stopped=raw.get('charging') is True or raw.get('off') is True or raw.get('gear') in ('P','p')
        if (not _fresh(stamp,observed) or raw.get('state_time')!=stamp or raw.get('observed_at')!=observed
                or (raw.get('speed') is not None and number(raw.get('speed'))!=0) or not stopped or mileage is None):return None
        if odometer is not None and abs(mileage-odometer)>.01:return None
        odometer=mileage;stamps.append(stamp)
    stamps=sorted(set(stamps))
    if len(stamps)<2 or stamps[0]!=a or stamps[-1]!=b or any(y-x>180000 for x,y in zip(stamps,stamps[1:])):return None
    return dict(point=left,samples=[],reference=True,evidence=dict(source='stationary_between_trips',sample_count=0,outlier_count=0,
                stationary_samples=len(stamps),start_time=a,end_time=b,truncated=False))


def reference_candidate(raw,event):
    ref=raw.get('start_location_reference')
    if not isinstance(ref,dict):return None
    point=_point(ref.get('location'),trusted=True);start=event.get('start_time')
    stamp=number(ref.get('state_time'),1,32503680000000);age=number(ref.get('age_seconds'),0,300)
    if (not point or start is None or stamp is None or age is None or not _fresh(stamp,ref.get('observed_time'))
            or not 0<=start-stamp<=300000 or abs((start-stamp)/1000-age)>1):return None
    boundaries=[_point(raw.get(side+'_location')) for side in ('start','end')]
    distances=[_distance(point,p) for p in boundaries if p is not None]
    return dict(point=point,time=stamp,age_seconds=age,boundary_distance_m=round(max(distances),1) if distances else None)


def _saved_reference(db,vehicle,event,raw):
    candidate=reference_candidate(raw,event)
    if not candidate:return None
    point=candidate['point'];stamp=candidate['time'];age=candidate['age_seconds'];start,end=event['start_time'],event['end_time']
    left,right=_telemetry(raw,'start'),_telemetry(raw,'end');mileage=number(left.get('odometer'))
    if (mileage is None or number(right.get('odometer'))!=mileage or left.get('off') is not True or right.get('off') is not True
            or left.get('charging') is not True or not _fresh(left.get('state_time'),left.get('observed_at'))
            or not _fresh(right.get('state_time'),right.get('observed_at'))):return None
    # A retained reference cannot overrule contradictory contemporaneous coordinates.
    for side in ('start','end'):
        boundary=_point(raw.get(side+'_location'))
        if boundary and _distance(boundary,point)>RADIUS_M:return None
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='report_observations'").fetchone():return None
    rows=db.execute('SELECT state_time,observed_at,CASE WHEN length(CAST(normalized_payload AS BLOB))<=? THEN normalized_payload END FROM report_observations WHERE vehicle=? AND state_time>=? AND state_time<=? ORDER BY state_time LIMIT ?', (MAX_TELEMETRY_BYTES,vehicle,start,end,MAX_SAMPLES+1))
    stamps=[]
    for index,(time,observed,encoded) in enumerate(rows):
        if index>=MAX_SAMPLES:return None
        check_cancelled();sample=_summary(encoded)
        if (not _fresh(time,observed) or sample.get('state_time')!=time or sample.get('observed_at')!=observed
                or number(sample.get('odometer'))!=mileage or sample.get('off') is not True
                or sample.get('speed') is not None and number(sample.get('speed'))!=0):return None
        stamps.append(time)
    stamps=sorted(set(stamps))
    if (len(stamps)<2 or stamps[0]-start>180000 or end-stamps[-1]>180000
            or any(b-a>180000 for a,b in zip(stamps,stamps[1:]))):return None
    return dict(point=point,samples=[],reference=True,evidence=dict(source='saved_precharge_reference',sample_count=0,outlier_count=0,
                reference_age_seconds=age,stationary_samples=len(stamps),start_time=stamp,end_time=end,truncated=False))


def resolve(db, vehicle, event):
    """Fixed-anchor clusters prevent drift chaining across distinct sites."""
    start,end=event.get('start_time'),event['end_time'];samples=[];truncated=False
    if start is not None and start<=end and db.execute("SELECT 1 FROM sqlite_master WHERE name='observations'").fetchone():
        rows=db.execute('SELECT state_time,observed_time,CASE WHEN length(CAST(location AS BLOB))<=8192 THEN location END FROM observations WHERE vehicle=? AND state_time>=? AND state_time<=? ORDER BY state_time,observed_time DESC,id DESC LIMIT ?', (vehicle,start,end,MAX_SAMPLES+1)).fetchall()
        truncated=len(rows)>MAX_SAMPLES;seen=set()
        for stamp,observed,encoded in rows[:MAX_SAMPLES]:
            check_cancelled();raw=_summary(encoded);point=_point(raw,trusted=True)
            if point and _fresh(stamp,observed) and stamp not in seen:
                samples.append(dict(time=stamp,point=point));seen.add(stamp)
    evidence=dict(source='unknown',sample_count=len(samples),outlier_count=0,truncated=truncated)
    result=dict(point=None,samples=samples,reference=True,evidence=evidence)
    if truncated:evidence['source']='sample_limit';return result
    if not samples:
        row=db.execute('SELECT CASE WHEN length(CAST(summary AS BLOB))<=? THEN summary END FROM monitor_events WHERE vehicle=? AND id=?',(MAX_SUMMARY_BYTES,vehicle,event['id'])).fetchone()
        raw=_summary(row[0]) if row else {}
        candidate=reference_candidate(raw,event)
        if candidate:result['reference_candidate']=candidate
        reference=_saved_reference(db,vehicle,event,raw)
        if reference:return reference
        inferred=_stationary_between(db,vehicle,event)
        if inferred:return inferred
        # Frozen trusted boundaries are still historical evidence, never current GPS.
        for side in ('start','end'):
            point=_point(raw.get(side+'_location'),trusted=True);stamp=event.get(side+'_time')
            if point and stamp is not None:samples.append(dict(time=stamp,point=point))
        if not samples:return result
        evidence['sample_count']=len(samples);evidence['source']='charge_boundaries'
    clusters=[]
    for sample in samples:
        nearby=[( _distance(sample['point'],c[0]['point']),i) for i,c in enumerate(clusters)]
        distance,index=min(nearby) if nearby else (float('inf'),None)
        if distance<=RADIUS_M:clusters[index].append(sample)
        else:clusters.append([sample])
    winner=max(clusters,key=len)
    if len(winner)/len(samples)<.8:
        evidence['source']='conflict';return result
    # Choose an actual point nearest the centre, rather than inventing a GPS sample.
    center=(sum(s['point'][0] for s in winner)/len(winner),sum(s['point'][1] for s in winner)/len(winner))
    for sample in samples:sample['outlier']=sample not in winner
    representative=min(winner,key=lambda s:_distance(s['point'],center))
    stable=len(winner)>=2 and max(s['time'] for s in winner)-min(s['time'] for s in winner)>=60000
    if evidence['source']!='charge_boundaries':evidence['source']='charge_samples' if stable else 'single_sample'
    evidence.update(outlier_count=len(samples)-len(winner),start_time=min(s['time'] for s in winner),end_time=max(s['time'] for s in winner))
    result.update(point=representative['point'],reference=not stable or evidence['source']=='charge_boundaries')
    return result
