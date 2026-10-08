"""Read-only archive timing diagnostics; no outage or vehicle-health inference."""
from collections import Counter
import math
import time

from .archive_reader import STALE_MS, _context
from .analysis_work import WorkDatabase
from .tracks import day_bounds
from .usage_reports import DAY, date_label

SLOT_MS=1800000
COUNT_KEYS=('new','revision','repeat','invalid')
ISSUE_KEYS=('stale','unknown_time','future_time','regression','revisited_time')


class DataQuality:
    def __init__(self,archive,clock=None):
        self.archive=archive
        self.clock=clock or (lambda:int(time.time()*1000))

    def query(self,scope,vehicle,start,end):
        _context(scope,vehicle)
        lower,_=day_bounds(start);_,requested_upper=day_bounds(end)
        if not 0<requested_upper-lower<=31*DAY:raise ValueError('请选择不超过 31 天的数据质量范围。')
        now=self.clock();upper=min(requested_upper,now+1)
        days=[]
        for stamp in range(lower,requested_upper,DAY):
            elapsed=max(0,min(DAY,upper-stamp))
            days.append(dict(date=date_label(stamp),start=stamp,reads=0,counts=dict.fromkeys(COUNT_KEYS,0),
                             first_read=None,last_read=None,read_slots=set(),new_slots=set(),
                             elapsed_slots=math.ceil(elapsed/SLOT_MS),status='future' if elapsed==0 else 'missing'))
        counts=Counter(dict.fromkeys(COUNT_KEYS,0));issues=Counter(dict.fromkeys(ISSUE_KEYS,0))
        sources=Counter(dict.fromkeys(('monitor','manual','unknown'),0))
        bins=[dict(label=label,count=0) for label in ('小于 0 秒','0–60 秒','大于 60 至 300 秒','大于 300 至 600 秒','大于 600 秒')]
        unknown_delay=0;gaps=[];previous=None;high_watermark=None;reads=0

        def add_gap(a,b,kind):
            if b-a>STALE_MS:gaps.append(dict(start=a,end=b,duration_seconds=(b-a)/1000,kind=kind))

        with WorkDatabase() as work:
            work.db.execute('CREATE TABLE delays(value)')
            if upper>lower:
                for record in self.archive.iter_metadata(scope,vehicle,lower,upper,limit=None):
                    observed,stamp=record['observed_at'],record['state_time'];reads+=1
                    day=days[(observed-lower)//DAY];day['reads']+=1;day['status']='observed'
                    if day['first_read'] is None:day['first_read']=observed
                    day['last_read']=observed;slot=(observed-day['start'])//SLOT_MS;day['read_slots'].add(slot)
                    add_gap(lower if previous is None else previous,observed,'leading' if previous is None else 'between')
                    previous=observed;sources[record['source']]+=1
                    for flag in record['flags']:
                        if flag in ISSUE_KEYS:issues[flag]+=1
                    if record['change']=='regression':issues['regression']+=1
                    if record['flags'] or stamp is None or record['change']=='regression':kind='invalid'
                    elif record['change'] in ('repeat','revision'):kind=record['change']
                    elif high_watermark is not None and stamp<=high_watermark:
                        kind='invalid';issues['revisited_time']+=1
                    else:kind='new'
                    if stamp is not None and not record['flags']:
                        high_watermark=max(high_watermark if high_watermark is not None else stamp,stamp)
                    counts[kind]+=1;day['counts'][kind]+=1
                    if kind=='new':day['new_slots'].add(slot)
                    delay=record['delay_seconds']
                    if delay is None or not math.isfinite(delay):unknown_delay+=1
                    else:
                        index=0 if delay<0 else 1 if delay<=60 else 2 if delay<=300 else 3 if delay<=600 else 4
                        bins[index]['count']+=1
                        if delay>=0:work.db.execute('INSERT INTO delays VALUES (?)',(delay,))
                add_gap(lower if previous is None else previous,upper,'empty' if previous is None else 'trailing')
            work.db.execute('CREATE INDEX delay_order ON delays(value)')
            count,maximum=work.db.execute('SELECT COUNT(*),MAX(value) FROM delays').fetchone()
            def percentile(p):
                return (work.db.execute('SELECT value FROM delays ORDER BY value LIMIT 1 OFFSET ?',
                                       (max(0,math.ceil(count*p)-1),)).fetchone()[0] if count else None)
            # Keep the original ascending Python sum, including rounding, without
            # retaining the samples or changing nearest-rank percentile semantics.
            mean=round(sum(value for value, in work.db.execute('SELECT value FROM delays ORDER BY value'))/count,3) if count else None
            delay_metrics=dict(bins=bins,unknown_count=unknown_delay,sample_count=count,
                               p50_seconds=percentile(.5),p95_seconds=percentile(.95),
                               max_seconds=maximum,mean_seconds=mean)
        for day in days:
            day['read_slots']=len(day['read_slots']);day['new_slots']=len(day['new_slots'])
        return dict(start_date=start,end_date=end,as_of=now,observed_until=upper if upper>lower else None,
                    reads=reads,counts=dict(counts),issues=dict(issues),sources=dict(sources),days=days,gaps=gaps,
                    gap_threshold_seconds=STALE_MS//1000,slot_minutes=SLOT_MS//60000,
                    delay=delay_metrics)
