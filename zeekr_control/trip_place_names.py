"""Owner-scoped manual names and conservative local names for reference places."""
import hashlib
import json
import math

from .commute_tags import _distance
from .geocoding import is_trusted_location, _without_units
from .usage_events import MAX_SUMMARY_BYTES
from .trip_place_geometry import cell, NEIGHBOURS
from collections import defaultdict


def anchor_key(place):
    coordinate='%.7f,%.7f' % (place['latitude'],place['longitude'])
    return 'place_name_'+hashlib.sha256(coordinate.encode()).hexdigest()


def cached_names(db, vehicle, events):
    """Read already-resolved addresses only; never call a geocoder here."""
    result={}
    ids=[e['id'] for e in events]
    for offset in range(0,len(ids),100):
        batch=ids[offset:offset+100]
        rows=db.execute('SELECT id,summary FROM monitor_events WHERE vehicle=? AND id IN ('+
                        ','.join('?' for _ in batch)+') AND length(CAST(summary AS BLOB))<=?',
                        (vehicle,*batch,MAX_SUMMARY_BYTES)).fetchall()
        for identity,encoded in rows:
            try:summary=json.loads(encoded)
            except (TypeError,ValueError,RecursionError):continue
            if not isinstance(summary,dict):continue
            for side in ('start','end'):
                label=summary.get(side+'_address')
                if not isinstance(label,str) or not label.strip() or len(label)>100 or any(ord(c)<32 for c in label):continue
                location=summary.get(side+'_location')
                if not is_trusted_location(location):
                    reference=summary.get(side+'_location_reference')
                    if not isinstance(reference,dict):continue
                    age=reference.get('age_seconds')
                    if type(age) not in (int,float) or not math.isfinite(age) or not 0<=age<=300:continue
                    location=reference.get('location')
                if not is_trusted_location(location) or location['coordinate_system']!='WGS84（社区解释）':continue
                label=_without_units(label,house_numbers=True).strip('· ')[:50]
                if not label or label in ('未知','位置未知'):continue
                result[(identity,side)]=dict(label=label if label.endswith('附近') else label+'附近',
                                          point=(location['latitude'],location['longitude']))
    return result


class TripPlaceNames:
    def __init__(self,store):self.store=store

    def regions(self,owner,vehicle):
        return [r for r in self.store.read(owner,vehicle,'place_names')['records'] if not r['deleted']]

    def apply(self,owner,vehicle,stats,rule):
        saved=self.store.read(owner,vehicle,'place_names')
        records=[r for r in saved['records'] if not r['deleted']]
        buckets=defaultdict(list)
        for record in records:buckets[cell((record['body']['latitude'],record['body']['longitude']))].append(record)
        for place in stats['places']:
            point=(place['latitude'],place['longitude'])
            place.update(name_key=anchor_key(place),name_source='reference',manual_name_id=None)
            bucket=cell(point)
            candidates=[r for delta in NEIGHBOURS for r in buckets.get(tuple(a+b for a,b in zip(bucket,delta)),())]
            nearby=sorted((_distance(point,(r['body']['latitude'],r['body']['longitude'])),r['id'],r)
                          for r in candidates if _distance(point,(r['body']['latitude'],r['body']['longitude']))<=r['body'].get('radius_m',150)+1e-7)
            if nearby:
                record=nearby[0][2];place.update(label=record['body']['name'],name_source='manual',manual_name_id=record['id'],name_radius_m=record['body'].get('radius_m',150));continue
            matches=[]
            if not rule.get('deleted'):
                for key,label in (('home','家'),('work','公司')):
                    region=rule.get(key)
                    if region and _distance(point,(region['latitude'],region['longitude']))<=region['radius_m']:
                        matches.append(label)
            if len(matches)==1:place.update(label=matches[0],name_source='commute');continue
            label=place.pop('address_label',None)
            if label:place.update(label=label,name_source='address')
        for place in stats['places']:place.pop('address_label',None)
        return dict(stats,name_revision=saved['revision'],name_can_undo=saved['can_undo'])

    def preview(self,owner,vehicle,data,stats):
        place=next((p for p in stats['places'] if p['id']==data.get('place_id')),None)
        if not place or place['name_key']!=data.get('place_key'):raise ValueError('地点分组已变化，请重新读取后命名。')
        name=data.get('name');radius=data.get('radius_m',150)
        if not isinstance(name,str) or not 1<=len(name.strip())<=40 or any(ord(c)<32 for c in name):raise ValueError('地点名称需为 1–40 字，不能含换行或控制字符。')
        if type(radius) is not int or not 25<=radius<=150:raise ValueError('命名范围应为 25–150 米的整数。')
        saved=self.store.read(owner,vehicle,'place_names')
        if data.get('revision')!=saved['revision']:raise ValueError('地点名称已有更新，请重新读取。')
        identity=place['manual_name_id'] or place['name_key']
        old=next((r for r in saved['records'] if r['id']==identity and not r['deleted']),None)
        anchor=(old['body']['latitude'],old['body']['longitude']) if old else (place['latitude'],place['longitude'])
        extent=max(radius,old['body'].get('radius_m',150) if old else radius)
        affected={}
        for sample in stats.get('_endpoints',[]):
            distance=_distance(anchor,sample['point'])
            if distance<=extent+1e-7:
                row=affected.setdefault(sample['event_id'],dict(id=sample['event_id'],sides=[],within_range=False))
                row['sides'].append(sample['side']);row['within_range']|=distance<=radius+1e-7
        conflicts=[dict(name=r['body']['name'],radius_m=r['body'].get('radius_m',150)) for r in saved['records']
                   if not r['deleted'] and r['id']!=identity and _distance(anchor,(r['body']['latitude'],r['body']['longitude']))<=radius+r['body'].get('radius_m',150)]
        body=dict(name=name.strip(),latitude=anchor[0],longitude=anchor[1],radius_m=radius)
        evidence=dict(owner=owner,vehicle=vehicle,identity=identity,body=body,revision=saved['revision'],
                      samples=stats.get('_endpoints',[]),records=saved['records'])
        token=hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        return dict(preview_token=token,affected_count=len(affected),affected=list(affected.values()),conflicts=conflicts,
                    radius_m=radius,name_revision=saved['revision']),identity,body

    def update(self,owner,vehicle,data,stats,guard=None):
        action=data.get('action')
        if action in ('place-name-preview','place-name-save'):
            preview,identity,body=self.preview(owner,vehicle,data,stats)
            if action=='place-name-preview':
                if guard:guard()
                return preview
            if data.get('preview_token')!=preview['preview_token']:raise ValueError('命名预览已变化，请重新预览后保存。')
            saved=self.store.change(owner,vehicle,'place_names','save',identity,body,data.get('revision'),guard=guard)
            return dict(name_revision=saved['revision'],name_can_undo=saved['can_undo'])
        if action=='place-name-undo':
            saved=self.store.change(owner,vehicle,'place_names','undo',None,None,data.get('revision'),guard=guard)
        else:
            place=next((p for p in stats['places'] if p['id']==data.get('place_id')),None)
            if not place or place['name_key']!=data.get('place_key'):
                raise ValueError('地点分组已变化，请重新读取后命名。')
            identity=place['manual_name_id'] or place['name_key']
            body=None
            if action=='place-name-clear' and place['manual_name_id']:operation='delete'
            else:raise ValueError('地点名称操作无效。')
            saved=self.store.change(owner,vehicle,'place_names',operation,identity,body,data.get('revision'),guard=guard)
        return dict(name_revision=saved['revision'],name_can_undo=saved['can_undo'])


def current_location_name(location, regions, rule, addresses):
    """Estimate a nearby name from local evidence in the same coordinate system."""
    if not is_trusted_location(location) or location['coordinate_system'] != 'WGS84（社区解释）':
        return None
    point = (location['latitude'], location['longitude'])
    nearby = sorted((_distance(point, (r['body']['latitude'], r['body']['longitude'])), r['body']['name'])
                    for r in regions if _distance(point, (r['body']['latitude'], r['body']['longitude'])) <= r['body'].get('radius_m', 150))
    label = nearby[0][1] if nearby else None
    if not label and not rule.get('deleted'):
        matches = [name for key, name in (('home', '家'), ('work', '公司'))
                   if rule.get(key) and _distance(point, (rule[key]['latitude'], rule[key]['longitude'])) <= rule[key]['radius_m']]
        if len(matches) == 1:
            label = matches[0]
    if not label:
        nearby = sorted((_distance(point, value['point']), value['label']) for value in addresses.values()
                        if _distance(point, value['point']) <= 150)
        label = nearby[0][1] if nearby else None
    return label if not label or label.endswith('附近') else label + '附近'
