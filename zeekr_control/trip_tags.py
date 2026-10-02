"""Private trip annotations and evidence-limited comparisons of like trips."""
import hashlib
from collections import defaultdict
from statistics import median

from .usage_events import UsageEvents
from .usage_reports import period_window
from .commute_tags import CommuteTags
from .trip_places import TripPlaces
from .trip_place_names import TripPlaceNames


def describe(values):
    values=[v for v in values if v is not None]
    return dict(samples=len(values),mean=round(sum(values)/len(values),6) if values else None,
                median=round(median(values),6) if values else None,
                minimum=min(values) if values else None,maximum=max(values) if values else None)


def comparison(tag,events):
    complete=[row for row in events if not row['partial']]
    eligible=[row for row in events if row['estimated_kwh'] is not None and row['distance_km'] is not None
              and row['distance_km']>=10 and row['soc_delta'] is not None and -row['soc_delta']>=3]
    distance=sum(row['distance_km'] for row in eligible)
    return dict(tag=tag,count=len(events),complete_count=len(complete),partial_count=len(events)-len(complete),
        distance_km=describe(row['distance_km'] for row in events),
        duration_seconds=describe(row['duration_seconds'] for row in events),
        soc_consumed=describe(-row['soc_delta'] if row['soc_delta'] is not None and row['soc_delta']<=0 else None for row in events),
        estimated_kwh=describe(row['estimated_kwh'] for row in events),
        efficiency=dict(value=round(sum(row['estimated_kwh'] for row in eligible)/distance*100,6) if distance else None,
                        samples=len(eligible),distance_km=round(distance,6) if eligible else None))


class TripTags:
    def __init__(self,store,database):
        self.store=store;self.events=UsageEvents(database);self.commute=CommuteTags(store,database);self.places=TripPlaces(database);self.place_names=TripPlaceNames(store)

    def update(self,owner,vehicle,data,guard=None):
        action=data.get('action');identity=data.get('id');body=None
        if isinstance(action,str) and action.startswith('place-name-'):
            stats=None
            if action!='place-name-undo':
                if not isinstance(data.get('date'),str):raise ValueError('请选择地点统计月份。')
                window=period_window('month',data.get('date'))
                events=[r for r in self.events.between(vehicle,window['start'],window['end'])['events'] if r['kind']=='trip_end']
                stats=self.place_names.apply(owner,vehicle,self.places.query(vehicle,events),self.commute.rule(owner,vehicle))
            return self.place_names.update(owner,vehicle,data,stats,guard=guard)
        if isinstance(action,str) and action.startswith('commute-'):
            if action in ('commute-exclude','commute-include'):
                event_id=data.get('event_id')
                event=self.events.get(vehicle,event_id)
                if event['kind']!='trip_end':raise ValueError('请选择已结束行程。')
                self.commute.exclude(owner,vehicle,event_id,action=='commute-exclude',guard=guard)
                return dict(id=event_id)
            return self.commute.update(owner,vehicle,data,guard=guard)
        if action=='save':
            event_id=data.get('event_id')
            event=self.events.get(vehicle,event_id)
            if event['kind']!='trip_end':raise ValueError('只能给已结束行程添加标签。')
            expected='tags_'+hashlib.sha256(event_id.encode()).hexdigest()
            if identity and identity!=expected:raise ValueError('行程关联已变化，请重新选择。')
            identity=expected
            labels=data.get('tags')
            if not isinstance(labels,list) or len(labels)>10:raise ValueError('每趟行程最多 10 个标签。')
            tags=[]
            for tag in labels:
                if not isinstance(tag,str) or not 1<=len(tag.strip())<=24 or any(ord(c)<32 for c in tag):
                    raise ValueError('标签需为 1–24 字，不能含换行或控制字符。')
                tag=tag.strip()
                if tag not in tags:tags.append(tag)
            note=data.get('note','')
            if not isinstance(note,str) or len(note)>1000:raise ValueError('行程备注需不超过 1000 字。')
            saved=self.store.read(owner,vehicle,'tags')
            vocabulary={tag for record in saved['records'] if not record['deleted'] and record['id']!=identity
                        for tag in record['body']['tags']}
            if len(vocabulary|set(tags))>200:raise ValueError('当前车辆最多保留 200 种标签，请先整理已有标签。')
            body=dict(event_id=event_id,tags=tags,note=note.strip())
        saved=self.store.change(owner,vehicle,'tags',action,identity,body,data.get('revision'),guard=guard)
        return dict(id=identity,revision=saved['revision'],can_undo=saved['can_undo'])

    def query(self,owner,vehicle,date,guard=None):
        window=period_window('month',date)
        events=[row for row in self.events.between(vehicle,window['start'],window['end'])['events'] if row['kind']=='trip_end']
        place_statistics=self.place_names.apply(owner,vehicle,self.places.query(vehicle,events),self.commute.rule(owner,vehicle))
        saved=self.store.read(owner,vehicle,'tags')
        annotations={r['body']['event_id']:r for r in saved['records']}
        automatic=self.commute.decisions(owner,vehicle,events,guard=guard)
        rows=[];trash=[]
        for event in events:
            record=annotations.get(event['id']);body=record['body'] if record and not record['deleted'] else {}
            manual=body.get('tags',[])
            decision=automatic.get(event['id'])
            auto=bool(decision and decision[0]=='matched' and not decision[1])
            tags=list(manual)
            if auto and '通勤' not in tags:tags.append('通勤')
            rows.append(dict(event,tags=tags,manual_tags=manual,note=body.get('note',''),
                             automatic_commute=auto,commute_excluded=bool(decision and decision[1]),
                             commute_reason=decision[0] if decision and decision[0]!='matched' else None,
                             annotation_id=record['id'] if body else None))
            if record and record['deleted']:trash.append(dict(record['body'],id=record['id'],end_time=event['end_time']))
        rows.sort(key=lambda row:(row['end_time'],row['id']),reverse=True)
        members=defaultdict(list)
        for row in rows:
            for tag in row['tags']:members[tag].append(row)
        return dict(window=window,revision=saved['revision'],can_undo=saved['can_undo'],events=rows,
                    groups=[comparison(tag,members[tag]) for tag in sorted(members)],
                    suggested_tags=sorted({tag for record in saved['records'] if not record['deleted']
                                           for tag in record['body']['tags']}),
                    untagged_count=sum(not row['tags'] for row in rows),trash=trash,
                    commute_rule=self.commute.rule(owner,vehicle),place_statistics=place_statistics)
