"""Daily recall and reversible place interpretation over saved evidence only."""
from collections import Counter
import hashlib
import json
import re
import time

from .commute_tags import CommuteTags, _distance
from .parking_analytics import ParkingAnalytics
from .trip_place_names import TripPlaceNames, anchor_key
from .place_regions import contains
from .trip_places import TripPlaces, cluster_endpoints
from .tracks import day_bounds
from .usage_calendar import UsageCalendar
from .usage_events import UsageEvents, total
from .usage_reports import date_label


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


class DailyTimeline:
    def __init__(self,database,archive,store):
        self.events=UsageEvents(database)
        self.database=database
        self.archive=archive
        self.store=store
        self.calendar=UsageCalendar(database,archive,store=store)

    @staticmethod
    def _parking_place(position,places,regions):
        point=(position['latitude'],position['longitude'])
        grouped=cluster_endpoints([dict(event_id='parking',side='end',time=0,point=point)],regions)
        place=grouped['places'][0]
        region=next((r for r in regions if r['id']==place['name_region_id']),None)
        if region:
            return dict(latitude=place['latitude'],longitude=place['longitude'],
                        label=region['body']['name'],name_source='manual')
        # Automatic nearby context may be reused, but manual names only apply
        # inside their saved radius, as resolved by the shared endpoint matcher.
        nearby=[p for p in places if p['name_source']!='manual' and
                _distance(point,(p['latitude'],p['longitude']))<=150]
        if nearby:return min(nearby,key=lambda p:_distance(point,(p['latitude'],p['longitude'])))
        return dict(latitude=point[0],longitude=point[1],label='未命名地点',name_source='reference')

    def _interpret(self, owner, vehicle, place, identity, side, saved):
        if place is None:
            return dict(key=None,label='位置未知',source='unknown',decision='unresolved',issues=['missing_position'])
        result=dict(key=anchor_key(place),label=place['label'] if place['name_source']!='reference' else '未命名地点',
                    source=place['name_source'],decision='automatic',issues=[],
                    latitude=place['latitude'],longitude=place['longitude'])
        if result['source']=='reference':result['source']='unknown'
        candidate=result['label']
        result['candidate']=candidate
        if place.get('candidate_conflict'):result['issues'].append('candidate_conflict')
        regions=saved.get('_regions',[])
        nearby=[r for r in regions if contains(r['body'],(result['latitude'],result['longitude']))]
        if len(nearby)>1:result['issues'].append('adjacent_conflict')
        if '_decisions' not in saved:
            saved['_decisions']={};saved['_remembered']=[]
            for r in saved['records']:
                if r['deleted']:continue
                body=r['body'];saved['_decisions'].setdefault((body['record_id'],body['side']),body)
                if body.get('remember') and body.get('action')=='reject':saved['_remembered'].append(body)
        for body in saved['_remembered']:
            if (result['source']!='manual' and body.get('candidate')==candidate
                    and _distance((result['latitude'],result['longitude']),(body['latitude'],body['longitude']))<=150):
                result.update(label='未命名地点',source='unknown',decision='rejected',key=body['key'])
        chosen=saved['_decisions'].get((identity,side))
        if chosen:
            result['key']=chosen.get('target_key') or chosen['key']
            if chosen['action']=='reject':
                if chosen['candidate']==candidate and result['source']!='manual':result.update(label='未命名地点',source='unknown',decision='rejected')
            else:
                target=next((r for r in regions if r['id']==chosen.get('target_key')),None)
                result.update(label=target['body']['name'] if target else chosen['name'],source='manual',decision='confirmed')
        if result['source']=='manual' or result['decision'] in ('confirmed','rejected'):result['issues']=[]
        if result['source']=='unknown' and result['decision']!='rejected':result['issues'].append('missing_name')
        return result

    def _records(self, scope, vehicle, owner, start_date, end_date):
        lower,_=day_bounds(start_date);_,upper=day_bounds(end_date)
        now=int(time.time()*1000)
        found=self.events.between(vehicle,lower,upper,overlap=True)
        events=[e for e in found['events'] if e['end_time']<=now]
        names=TripPlaceNames(self.store)
        # All event endpoints use the established 150m fixed-centre rule.
        named=[dict(e) for e in events]
        stats=TripPlaces(self.database).query(vehicle,named,names.regions(owner,vehicle),include_samples=True)
        stats=names.apply(owner,vehicle,stats,CommuteTags(self.store,self.database).rule(owner,vehicle))
        places={p['id']:p for p in stats['places']}
        corrections=self.store.read(owner,vehicle,'place_corrections')
        corrections['_regions']=names.regions(owner,vehicle)
        bills=self.store.read(owner,vehicle,'charges')
        booked={r['body']['event']['id']:dict(r['body'],id=r['id']) for r in bills['records']
                if not r['deleted'] and isinstance(r['body'].get('event'),dict)}
        positions={(sample['event_id'],sample['side']):sample for sample in stats['_endpoints']}
        records=[]
        for event in named:
            row=dict(event,type='trip' if event['kind']=='trip_end' else 'charge',status='ended')
            for side in ('start','end'):
                row[side+'_place']=self._interpret(owner,vehicle,places.get(event.get(side+'_place')),event['id'],side,corrections)
            point=positions.get((event['id'],'end')) or positions.get((event['id'],'start'))
            row['_position']=dict(latitude=point['point'][0],longitude=point['point'][1],state_time=point['time']) if point else None
            row['bill']=booked.get(event['id']) if row['type']=='charge' else None
            records.append(row)
        parked=ParkingAnalytics(self.archive).query(scope,vehicle,start_date,end_date,context_days=1)
        for session in parked['sessions']:
            if session['end_time']>now:continue
            row={k:session[k] for k in ('start_time','end_time','duration_seconds','sample_count','reasons','reason_labels')}
            # A parking sample itself must have a trusted endpoint; never borrow a trip's location.
            point=None;observed_position=None
            with self.events.connect() as db:
                if db is not None and db.execute("SELECT 1 FROM sqlite_master WHERE name='observations'").fetchone():
                    from .trip_endpoints import endpoint
                    match=endpoint(db,vehicle,row['start_time'],min(row['end_time'],row['start_time']+180000),True)
                    if match:
                        observed_position=dict(latitude=match[1][0],longitude=match[1][1],state_time=match[0])
                        point=self._parking_place(observed_position,stats['places'],corrections['_regions'])
            row['_position']=observed_position
            row.update(id='parking_'+digest(session['id'])[:32],type='parking',status='observed',partial=bool(session['reasons']),bill=None)
            row['start_place']=self._interpret(owner,vehicle,point,row['id'],'start',corrections)
            row['end_place']=self._interpret(owner,vehicle,point,row['id'],'end',corrections)
            records.append(row)
        records.sort(key=lambda r:(r['start_time'] if r['start_time'] is not None else r['end_time'],r['id']))
        for row in records:
            row['date']=date_label(row['end_time'])
            row['cross_midnight']=row['start_time'] is not None and date_label(row['start_time'])!=row['date']
        return records,dict(correction_revision=corrections['revision'],correction_can_undo=corrections['can_undo'],
                            name_revision=stats['name_revision'],ledger_revision=bills['revision'],history_quality=found['unreadable_or_undated'])

    @staticmethod
    def _positions(records,enabled):
        for row in records:
            actual=row.pop('_position',None)
            if enabled and actual:row['position']=actual
            for side in ('start','end'):
                row[side+'_place'].pop('latitude',None);row[side+'_place'].pop('longitude',None)

    def query(self,scope,vehicle,date,owner=None,positions=False):
        owner=owner or scope
        lower,upper=day_bounds(date)
        records,meta=self._records(scope,vehicle,owner,date,date)
        month=self.calendar.query(scope,vehicle,date,owner=owner)
        day=next(d for d in month['days'] if d['date']==date)
        ended=[r for r in records if lower<=r['end_time']<upper and r['type']!='parking']
        trips=[r for r in ended if r['type']=='trip']
        summary=dict(distance_km=total(r['distance_km'] for r in trips),duration_seconds=total(r['duration_seconds'] for r in trips),
                     trip_count=len(trips),charge_count=sum(r['type']=='charge' for r in ended),
                     actual_cents=day['actual_cents'],pending_count=day['pending_count'],unpriced_count=day['unpriced_count'])
        revision=digest(dict(records=records,summary=summary,meta=meta))
        self._positions(records,positions)
        known=[dict(key=r['id'],name=r['body']['name']) for r in TripPlaceNames(self.store).regions(owner,vehicle)]
        return dict(date=date,records=records,known_places=known,summary=summary,coverage={k:day[k] for k in
                    ('coverage','reads','effective_states','first_read','last_read')},revision=revision,**meta)

    def update(self,owner,vehicle,data,scope=None,guard=None):
        saved=self.store.read(owner,vehicle,'place_corrections')
        if data.get('operation')=='undo':
            changed=self.store.change(owner,vehicle,'place_corrections','undo',None,None,data.get('revision'),guard=guard)
            return dict(revision=changed['revision'])
        records,meta=self._records(scope or owner,vehicle,owner,data.get('date'),data.get('date'))
        row=next((r for r in records if r['id']==data.get('record_id')),None)
        side=data.get('side')
        if row is None or side not in ('start','end'):raise ValueError('记录已变化，请重新读取。')
        place=row[side+'_place']
        if not place['key']:raise ValueError('没有可信位置，不能确认地点归属。')
        action=data.get('action')
        if action=='confirm' and place['source']=='unknown':raise ValueError('名称未知，请先填写地点名称。')
        if action=='reject' and place['source']=='manual':raise ValueError('人工名称请改归属，不作为自动匹配拒绝。')
        if action not in ('confirm','assign','reject'):raise ValueError('地点操作无效。')
        target_key=data.get('target_key') if action=='assign' else None
        target=None
        if target_key:
            target=next((r for r in TripPlaceNames(self.store).regions(owner,vehicle) if r['id']==target_key),None)
            if target is None:raise ValueError('目标地点已变化，请重新读取。')
        name=target['body']['name'] if target else data.get('name') if action=='assign' else place['label']
        if action!='reject' and (not isinstance(name,str) or not 1<=len(name.strip())<=40 or any(ord(c)<32 for c in name)):
            raise ValueError('地点名称需为 1–40 字，不能含控制字符。')
        if data.get('revision')!=saved['revision']:raise ValueError('地点修正已更新，请重新读取。')
        body=dict(record_id=row['id'],side=side,action=action,name=name.strip(),candidate=place.get('candidate',place['label']),
                  key=place['key'],target_key=target_key,latitude=place['latitude'],longitude=place['longitude'],remember=action=='reject' and data.get('remember') is True)
        affected=[r['id'] for r in records if r['id']==row['id'] or body['remember'] and any(
            p['key'] and p.get('candidate')==body['candidate'] and _distance((p['latitude'],p['longitude']),
            (body['latitude'],body['longitude']))<=150 for p in (r['start_place'],r['end_place']))]
        token=digest(dict(body=body,records=records,meta=meta,owner=owner,vehicle=vehicle))
        if guard:guard()
        if data.get('operation')=='preview':return dict(preview_token=token,affected_count=len(set(affected)),remember=body['remember'])
        if data.get('operation')!='save' or data.get('preview_token')!=token:raise ValueError('预览已变化，请重新预览。')
        identity='correction_'+digest([row['id'],side])[:40]
        changed=self.store.change(owner,vehicle,'place_corrections','save',identity,body,saved['revision'],guard=guard)
        return dict(revision=changed['revision'])

    def history(self,scope,vehicle,start,end,key,cursor=None,owner=None):
        lower,_=day_bounds(start);_,upper=day_bounds(end)
        if not 0<upper-lower<=31*86400000:raise ValueError('地点历史请选择不超过 31 天。')
        if not isinstance(key,str) or not re.fullmatch(r'place_name_[a-f0-9]{64}',key):raise ValueError('地点标识无效。')
        rows,meta=self._records(scope,vehicle,owner or scope,start,end)
        selected,_=self._records(scope,vehicle,owner or scope,end,end)
        anchor=next((r[side+'_place'] for r in selected for side in ('start','end') if r[side+'_place']['key']==key),None)
        if anchor is None:
            anchor=next((r[side+'_place'] for r in rows for side in ('start','end') if r[side+'_place']['key']==key),None)
        def matches(place):
            if place['key']==key:return True
            # Proximity reconciles automatic cluster anchors across date ranges.
            # Explicit names and corrections already define membership; distance
            # must not merge nearby regions or override a user's assignment.
            return bool(anchor and place['key'] and
                        all(p['source']!='manual' and p['decision']=='automatic' for p in (place,anchor)) and
                        _distance((place['latitude'],place['longitude']),(anchor['latitude'],anchor['longitude']))<=150)
        rows=[r for r in rows if any(matches(p) for p in (r['start_place'],r['end_place']))]
        revision=digest(dict(rows=rows,meta=meta))
        offset=0
        if cursor:
            try:
                version,index=cursor.split(':');offset=int(index)
                if version!=revision or offset<0:raise ValueError()
            except (ValueError,AttributeError):raise ValueError('历史已变化，请从第一页重新读取。') from None
        page=rows[offset:offset+30];self._positions(page,False)
        return dict(records=page,count=len(rows),revision=revision,next_cursor=f'{revision}:{offset+30}' if offset+30<len(rows) else None,**meta)

    def year(self,scope,vehicle,year,owner=None):
        if not isinstance(year,str) or not re.fullmatch(r'20\d{2}',year):raise ValueError('年份无效。')
        months=[];days=[];places=Counter();parking_counts=Counter();parking_info={}
        for month in range(1,13):
            result=self.calendar.query(scope,vehicle,f'{year}-{month:02d}-01',owner=owner or scope)
            months.append(dict(month=f'{year}-{month:02d}',**result['totals']))
            days.extend(result['days'])
            for p in result['totals'].get('parking_places',[]):
                parking_counts[p['key']]+=1;parking_info[p['key']]=p
            for row in result['events']:
                if row['kind']=='trip_end' and row['end_date'].startswith(f'{year}-{month:02d}') and row.get('end_label') not in (None,'终点未知','未命名地点'):
                    places[row['end_label']]+=1
        totals={key:total(m[key] for m in months) for key in ('distance_km','actual_cents')}
        totals.update(usage_days=sum(d['trip_count']>0 for d in days),trip_count=sum(m['trip_count'] for m in months),
                      charge_count=sum(m['charge_count'] for m in months),unpriced_count=sum(m['unpriced_count'] for m in months),
                      pending_count=sum(m['pending_count'] for m in months))
        return dict(year=year,days=days,months=months,totals=totals,
                    frequent_places=[dict(label=k,arrivals=v) for k,v in places.most_common(10)],
                    frequent_parking_places=[dict(parking_info[k],count=v) for k,v in parking_counts.most_common(10)],
                    correction_revision=self.store.read(owner or scope,vehicle,'place_corrections')['revision'])
