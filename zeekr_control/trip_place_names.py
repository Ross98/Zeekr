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
                          for r in candidates)
            if nearby and nearby[0][0]<=stats['radius_m']:
                record=nearby[0][2];place.update(label=record['body']['name'],name_source='manual',manual_name_id=record['id']);continue
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

    def update(self,owner,vehicle,data,stats,guard=None):
        action=data.get('action')
        if action=='place-name-undo':
            saved=self.store.change(owner,vehicle,'place_names','undo',None,None,data.get('revision'),guard=guard)
        else:
            place=next((p for p in stats['places'] if p['id']==data.get('place_id')),None)
            if not place or place['name_key']!=data.get('place_key'):
                raise ValueError('地点分组已变化，请重新读取后命名。')
            identity=place['manual_name_id'] or place['name_key']
            body=None
            if action=='place-name-save':
                name=data.get('name')
                if not isinstance(name,str) or not 1<=len(name.strip())<=40 or any(ord(c)<32 for c in name):
                    raise ValueError('地点名称需为 1–40 字，不能含换行或控制字符。')
                body=dict(name=name.strip(),latitude=place['latitude'],longitude=place['longitude'])
                # Keep the saved anchor fixed when editing a name found in another month.
                if place['manual_name_id']:
                    old=next((r for r in self.store.read(owner,vehicle,'place_names')['records'] if r['id']==identity),None)
                    if old is None:raise ValueError('地点名称已有更新，请重新读取。')
                    body.update(latitude=old['body']['latitude'],longitude=old['body']['longitude'])
                operation='save'
            elif action=='place-name-clear' and place['manual_name_id']:operation='delete'
            else:raise ValueError('地点名称操作无效。')
            saved=self.store.change(owner,vehicle,'place_names',operation,identity,body,data.get('revision'),guard=guard)
        return dict(name_revision=saved['revision'],name_can_undo=saved['can_undo'])
