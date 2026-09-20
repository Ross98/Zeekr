"""Bounded charging comparisons on observed SOC, with explicit discontinuities."""
import json

from .usage_events import UsageEvents,number
from .usage_reports import period_window

MAX_POINTS=50000
MAX_PAYLOAD=65536
METRICS=('power_kw','outside_temp','inside_temp','elapsed_seconds')


def temperature(point,key,stamp):
    metric=point.get(key)
    if not isinstance(metric,dict) or metric.get('validity')!='valid':return None
    value=number(metric.get('value'),-80,100)
    if metric.get('state_time') is not None and number(metric['state_time'],1,32503680000000)!=stamp:return None
    field=metric.get('field_time')
    if field is not None:
        field=number(field,1,32503680000000)
        if field is None or not -30000<=stamp-field<=180000:return None
    return value


def project(point,stamp,observed,decoder):
    if (not isinstance(point,dict) or number(point.get('state_time'),1,32503680000000)!=stamp
            or number(point.get('observed_at'),1,32503680000000)!=observed
            or not -30000<=observed-stamp<=180000 or point.get('charging') is not True
            or point.get('charging_mode') not in ('ac','dc') or not isinstance(decoder,str) or not 0<len(decoder)<=80):
        return None
    soc=number(point.get('soc'),0,100)
    if soc is None:return None
    mode=point['charging_mode'];source=point.get('power_source')
    power=number(point.get('power_kw'),0,2000) if source==('ac_ui' if mode=='ac' else 'dc_pile_ui') else None
    return dict(time=stamp,observed_at=observed,soc=soc,mode=mode,power_kw=power,
                power_source=source if power is not None else None,
                outside_temp=temperature(point,'outside_temp',stamp),inside_temp=temperature(point,'inside_temp',stamp))


def downsample(points,limit=600):
    if len(points)<=limit:return points
    mandatory={0,len(points)-1}
    for field in METRICS:
        valid=[i for i,p in enumerate(points) if p[field] is not None]
        if valid:mandatory.update((min(valid,key=lambda i:points[i][field]),max(valid,key=lambda i:points[i][field])))
    boundaries=set()
    for i in range(1,len(points)):
        if points[i]['lines']!=points[i-1]['lines']:boundaries.update((i-1,i))
    keep=set(mandatory)
    extras=sorted(boundaries-keep)
    remaining=limit-len(keep)
    if len(extras)>remaining:
        keep.update(extras[round(i*(len(extras)-1)/(remaining-1))] for i in range(remaining))
    else:keep.update(extras)
    available=[i for i in range(len(points)) if i not in keep]
    remaining=limit-len(keep)
    if remaining:
        keep.update(available[round(i*(len(available)-1)/max(1,remaining-1))] for i in range(remaining))
    return [points[i] for i in sorted(keep)]


class ChargeComparison:
    def __init__(self,database):self.events=UsageEvents(database)

    def options(self,vehicle,date):
        window=period_window('month',date)
        found=self.events.between(vehicle,window['start'],window['end'])
        return dict(window=window,events=[e for e in found['events'] if e['kind']=='charge_end'])

    def _session(self,vehicle,identity):
        event=self.events.get(vehicle,identity)
        if event['kind']!='charge_end':raise ValueError('请选择两次已结束充电。')
        points=[];quality=dict(reads=0,invalid=0,excluded=0,eligible=0,segments=0)
        result=dict(event=event,points=points,quality=quality)
        if event['start_time'] is None or event['end_time']<event['start_time']:return result
        previous=None;previous_decoder=None;broken=False;segment=-1
        with self.events.connect() as db:
            if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='report_observations'").fetchone():return result
            cursor=event['start_time']-1
            while True:
                rows=db.execute('SELECT state_time,observed_at,decoder_version,CASE WHEN length(CAST(normalized_payload AS BLOB))<=? '
                    'THEN normalized_payload END FROM report_observations WHERE vehicle=? AND state_time>? AND state_time<=? '
                    'ORDER BY state_time LIMIT 100',(MAX_PAYLOAD,vehicle,cursor,event['end_time'])).fetchall()
                if not rows:break
                for stamp,observed,decoder,encoded in rows:
                    cursor=stamp;quality['reads']+=1
                    if quality['reads']>MAX_POINTS:raise ValueError('充电观测超过 50000 条，无法安全载入对比。')
                    try:raw=json.loads(encoded)
                    except (ValueError,TypeError,RecursionError):
                        quality['invalid']+=1;broken=True;continue
                    row=project(raw,stamp,observed,decoder)
                    if row is None:
                        quality['excluded']+=1;broken=True;continue
                    continuous=(previous is not None and not broken and 0<stamp-previous['time']<=180000
                        and 0<=observed-previous['observed_at']<=180000 and row['soc']>=previous['soc']
                        and row['mode']==previous['mode'] and decoder==previous_decoder)
                    if not continuous:segment+=1
                    row['segment']=segment;points.append(row)
                    previous=row;previous_decoder=decoder;broken=False
        quality.update(eligible=len(points),segments=segment+1)
        return result

    @staticmethod
    def _align(session,common):
        raw=session['points']
        session['soc_range']=[min(p['soc'] for p in raw),max(p['soc'] for p in raw)] if raw else None
        session['modes']=sorted({p['mode'] for p in raw})
        session['power_sources']=sorted({p['power_source'] for p in raw if p['power_source']})
        points=[p for p in raw if common and common['low']<=p['soc']<=common['high']]
        timing=dict(minimum_seconds=None,maximum_seconds=None,reason='no_common_range')
        lower=[p for p in points if abs(p['soc']-common['low'])<.000001] if common else []
        upper=[p for p in points if abs(p['soc']-common['high'])<.000001] if common else []
        origin=lower[0]['time'] if lower else None
        if common:
            timing['reason']='boundary_not_observed'
            if not common['has_span']:timing['reason']='single_soc'
            elif lower and upper:
                path=[p for p in raw if lower[0]['time']<=p['time']<=upper[-1]['time']]
                if lower[-1]['time']>upper[0]['time'] or len({p['segment'] for p in path})!=1:
                    timing['reason']='gaps_or_reset'
                else:
                    timing.update(minimum_seconds=(upper[0]['time']-lower[-1]['time'])/1000,
                                  maximum_seconds=(upper[-1]['time']-lower[0]['time'])/1000,reason=None)
        session['timing']=timing
        for point in points:
            point['elapsed_seconds']=(point['time']-origin)/1000 if origin is not None and point['time']>=origin else None
        counters={field:0 for field in METRICS};previous=None
        for point in points:
            lines={}
            for field in METRICS:
                if previous is None or point['segment']!=previous['segment'] or previous[field] is None or point[field] is None:
                    counters[field]+=1
                lines[field]=counters[field] if point[field] is not None else None
            point['lines']=lines;previous=point
        session['matched_count']=len(points)
        session['peaks']={field:max((p[field] for p in points if p[field] is not None),default=None) for field in METRICS[:3]}
        session['points']=downsample(points)
        session['downsampled']=len(points)>len(session['points'])
        session['display_count']=len(session['points'])
        return session

    def query(self,vehicle,a,b):
        if a==b:raise ValueError('请选择两次不同的充电记录。')
        left,right=self._session(vehicle,a),self._session(vehicle,b)
        common=None
        if left['points'] and right['points']:
            low=max(min(p['soc'] for p in s['points']) for s in (left,right))
            high=min(max(p['soc'] for p in s['points']) for s in (left,right))
            if low<=high:common=dict(low=low,high=high,has_span=high>low)
        return dict(common=common,a=self._align(left,common),b=self._align(right,common))
