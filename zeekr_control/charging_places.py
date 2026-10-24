"""Charge venue corrections and summaries; raw events and bills remain untouched."""
from contextlib import nullcontext
import hashlib
import hmac
import json
import secrets
import time

from .analysis_cancel import check_cancelled
from .charging_locations import resolve, coordinates, RADIUS_M
from .charging_energy import summary as energy_summary
from .commute_tags import CommuteTags, _distance
from .trip_place_names import TripPlaceNames, cached_names
from .place_regions import RegionIndex
from .usage_events import UsageEvents, number, total
from .usage_reports import date_label

COLLECTION='charging_places'
# Names explicitly confirmed by the owner tolerate parking-area GPS drift.
# Fixed anchors still separate distant branches with identical names.
CONFIRMED_STATION_RADIUS_M=1000


def _key(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _text(value,required=False):
    if not isinstance(value,str) or len(value)>80 or any(ord(c)<32 for c in value) or required and not value.strip():
        raise ValueError('地点和站点名称需为单行文字，最多 80 字。')
    return value.strip()


class ChargingPlaces:
    def __init__(self, database, store):
        self.events=UsageEvents(database);self.store=store;self.secret=secrets.token_bytes(32)

    def _base(self, db, owner, vehicle, event):
        result=resolve(db,vehicle,event);point=result['point'];result.update(name='地点未知',name_source='unknown',station_name=None,station_source=None,group_key=None)
        candidate=result.get('reference_candidate');naming_point=point or (candidate['point'] if candidate else None)
        if not naming_point:return result
        place=dict(id='charge_location',label='地点未知',latitude=naming_point[0],longitude=naming_point[1],departures=0,arrivals=0)
        addresses=cached_names(db,vehicle,[event])
        nearby=[r for r in addresses.values() if _distance(naming_point,r['point'])<=RADIUS_M]
        if nearby:place['address_label']=min(nearby,key=lambda r:_distance(naming_point,r['point']))['label']
        named=TripPlaceNames(self.store).apply(owner,vehicle,dict(places=[place]),CommuteTags(self.store,self.events.path).rule(owner,vehicle))['places'][0]
        if not point:
            result['reference_candidate']['name']=named['label'];return result
        result.update(name=named['label'],name_source=named['name_source'] if named['name_source']!='reference' else 'unknown',
                      group_key='named:'+named['manual_name_id'] if named.get('manual_name_id') else None)
        return result

    def _resolved(self, owner, vehicle, events, saved=None):
        saved=saved or self.store.read(owner,vehicle,COLLECTION);overrides=sorted((r for r in saved['records'] if not r['deleted']),key=lambda r:(r['body'].get('version',0),r['updated_at'],r['id']),reverse=True);results={}
        named_regions=RegionIndex(TripPlaceNames(self.store).regions(owner,vehicle))
        with self.events.connect() as db:
            if db is None:return results
            for event in events:
                check_cancelled();r=self._base(db,owner,vehicle,event);anchor=r['point']
                single=next((x for x in overrides if x['body'].get('scope')=='single' and x['body'].get('event_id')==event['id']),None)
                matching=[x for x in overrides if x['body'].get('scope')=='place' and anchor and _distance(anchor,tuple(x['body']['anchor']))<=x['body']['radius_m']]
                region=matching[0] if matching else None
                converted=bool(single and region and region['body'].get('replace_single_event')==event['id'] and region['body'].get('version',0)>single['body'].get('version',0))
                chosen=region if converted else single or region
                if chosen:
                    body=chosen['body'];r.update(name=body['name'],name_source='manual',point=tuple(body['point']) if body['point'] else None,
                        station_name=body.get('station_name') or None,station_source='manual' if body.get('station_name') else None,
                        correction_id=chosen['id'],correction_scope=body['scope'],rule_anchor=body.get('anchor'),radius_m=body['radius_m'],reference=r['reference'] if body['point'] and tuple(body['point'])==anchor else False,
                        group_key=None)
                    effective_region=named_regions.pick(r['point']) if r['point'] else None
                    if effective_region:r['group_key']='named:'+effective_region['id']
                r['anchor']=anchor;r['event_id']=event['id'];results[event['id']]=r
        return results

    @staticmethod
    def _public(result, saved):
        candidate=result.get('reference_candidate') if result['point'] is None else None
        return dict(reference_candidate=dict(location=coordinates(candidate['point']),age_seconds=candidate['age_seconds'],boundary_distance_m=candidate.get('boundary_distance_m'),time=candidate['time'],name=candidate.get('name','地点未知')) if candidate else None,
                    event_id=result['event_id'],name=result['name'],name_source=result['name_source'],station_name=result['station_name'],
                    station_source=result['station_source'],location=coordinates(result['point']),reference=result['reference'],
                    evidence=result['evidence'],samples=[dict(time=s['time'],outlier=s.get('outlier',False),**coordinates(s['point'])) for s in result['samples']],
                    revision=saved['revision'],can_undo=saved['can_undo'],correction_scope=result.get('correction_scope'),
                    radius_m=result.get('radius_m',RADIUS_M))

    def timeline_places(self, owner, vehicle, events):
        """Shared charge labels; user naming never creates trusted GPS evidence."""
        from .trip_place_names import anchor_key
        resolved=self._resolved(owner,vehicle,events)
        keys=self._station_keys(events,resolved)
        result={}
        for event in events:
            r=resolved.get(event['id'])
            if not r or r['name_source']=='unknown':continue
            label=r['station_name'] or r['name'];point=r['point']
            key=anchor_key(dict(latitude=point[0],longitude=point[1])) if point else 'place_name_'+_key('charge:'+event['id'])
            place=dict(key=key,statistics_key=keys.get(event['id']) or r['group_key'] or key,
                       label=label,source=r['name_source'],decision='confirmed' if r['name_source']=='manual' else 'automatic',
                       candidate=label,issues=[],label_only=point is None,evidence='charge_place_confirmation' if r['name_source']=='manual' else r['evidence']['source'])
            if point:place.update(latitude=point[0],longitude=point[1])
            result[event['id']]=place
        return result

    def detail(self,owner,vehicle,identity):
        event=self.events.get(vehicle,identity)
        if event['kind']!='charge_end':raise ValueError('请选择已结束充电记录。')
        saved=self.store.read(owner,vehicle,COLLECTION)
        return self._public(self._resolved(owner,vehicle,[event],saved)[identity],saved)

    def apply(self,owner,vehicle,records):
        resolved=self._resolved(owner,vehicle,records);anchors=[]
        ordered=sorted(records,key=lambda r:(r['end_time'],r['id']))
        station_keys=self._station_keys(ordered,resolved)
        for row in ordered:
            r=resolved[row['id']];point=r['point'];key=station_keys.get(row['id']) or (r['group_key'] if point is not None else None)
            if key is None and point:
                match=next((a for a in anchors if _distance(a[1],point)<=RADIUS_M),None)
                if match:key=match[0]
                else:key='site:'+_key('%.6f,%.6f'%point);anchors.append((key,point))
            if not key:key='unlocated'
            row.update(place_label=r['name'],place_source=r['name_source'],place_reference=r['reference'] and point is not None,
                       place_key=key,place_unlocated=point is None,station_name=r['station_name'],station_source=r['station_source'],
                       location_quality=r['evidence']['source'])
        return self.summary(records)

    @staticmethod
    def _station_keys(ordered,resolved):
        stations={};keys={}
        for row in ordered:
            check_cancelled();r=resolved[row['id']]
            if r['name_source']!='manual' or r['station_source']!='manual' or not r['station_name']:continue
            identity=(r['name'],r['station_name']);group=stations.setdefault(identity,dict(anchors=[],missing=[]))
            point=r['point']
            if point is None:
                group['missing'].append(row['id']);continue
            matches=[a for a in group['anchors'] if _distance(a[1],point)<=CONFIRMED_STATION_RADIUS_M]
            if matches:key=min(matches,key=lambda a:_distance(a[1],point))[0]
            else:
                key='station:'+_key(json.dumps([*identity,'%.6f,%.6f'%point],ensure_ascii=False))
                group['anchors'].append((key,point))
            keys[row['id']]=key
        for identity,group in stations.items():
            # Missing GPS can join only an unambiguous manually confirmed station.
            if len(group['anchors'])>1:continue
            key=group['anchors'][0][0] if group['anchors'] else 'station:'+_key(json.dumps([*identity,None],ensure_ascii=False))
            for event_id in group['missing']:keys[event_id]=key
        return keys

    @staticmethod
    def summary(records):
        groups={}
        for row in records:
            key=row['place_key'];g=groups.setdefault(key,dict(key=key,name=row['place_label'],unlocated=row['place_unlocated'],records=[]))
            g['records'].append(row)
        output=[]
        for g in groups.values():
            rows=g.pop('records');billed=[r for r in rows if r.get('bill') and r['bill']['actual_cents'] is not None]
            paired=[r for r in billed if number(r['bill'].get('metered_kwh'),.000001,10000) is not None]
            energy=total(r['bill']['metered_kwh'] for r in paired);cost=total(r['bill']['actual_cents'] for r in paired)
            g.update(unlocated=all(r['place_unlocated'] for r in rows) and not g['key'].startswith('station:'),
                     **energy_summary(rows),
                     location_missing_count=sum(r['place_unlocated'] for r in rows),
                     charge_count=len(rows),known_count=len(billed),pending_count=len(rows)-len(billed),actual_cents=total(r['bill']['actual_cents'] for r in billed),
                     estimated_kwh=total(r.get('estimated_kwh') for r in rows),energy_samples=sum(r.get('estimated_kwh') is not None for r in rows),
                     metered_kwh=energy,paired_count=len(paired),cents_per_kwh=cost/energy if energy and cost is not None else None,
                     modes={mode:sum(r['mode']==mode for r in rows) for mode in ('ac','dc','unknown')},
                     station_names=sorted({r['station_name'] for r in rows if r['station_name']}),reference_count=sum(r['place_reference'] for r in rows))
            output.append(g)
        return sorted(output,key=lambda g:(g['unlocated'],-(g['actual_cents'] or 0),-g['charge_count'],g['key']))

    def _proposal(self,owner,vehicle,data):
        detail=self.detail(owner,vehicle,data.get('event_id'));revision=data.get('revision')
        if type(revision) is not int or revision!=detail['revision']:raise ValueError('地点记录已更新，请重新读取。')
        scope=data.get('scope');name=_text(data.get('name'),True);station=_text(data.get('station_name',''))
        if scope not in ('single','place'):raise ValueError('请选择仅本次或同地点记录。')
        lat,lon=data.get('latitude'),data.get('longitude');radius=data.get('radius_m',RADIUS_M)
        if lat is None and lon is None:point=None
        elif number(lat,-90,90) is None or number(lon,-180,180) is None or lat==lon==0:raise ValueError('请选择有效的 WGS84 地图位置。')
        else:point=[lat,lon]
        if type(radius) is not int or not 25<=radius<=150:raise ValueError('地点匹配范围须为 25–150 米。')
        event=self.events.get(vehicle,data['event_id']);raw=self._resolved(owner,vehicle,[event])[event['id']]
        saved=self.store.read(owner,vehicle,COLLECTION)
        anchor=raw['anchor'];existing_region=None
        if scope=='place':
            if anchor is None:raise ValueError('缺少历史定位，暂不能匹配同地点；可仅修正本次。')
            matches=[r for r in saved['records'] if not r['deleted'] and r['body'].get('scope')=='place'
                     and _distance(anchor,tuple(r['body']['anchor']))<=r['body']['radius_m']]
            if raw.get('correction_scope')=='place':existing_region=next(r for r in matches if r['id']==raw['correction_id'])
            elif matches:existing_region=max(matches,key=lambda r:(r['body'].get('version',0),r['updated_at'],r['id']))
            if existing_region:anchor=tuple(existing_region['body']['anchor'])
        identity=('event_' if scope=='single' else 'region_')+_key(event['id'] if scope=='single' else '%.6f,%.6f'%anchor)
        if existing_region:identity=existing_region['id']
        body=dict(event_id=event['id'],scope=scope,name=name,station_name=station,point=point,anchor=list(anchor) if anchor else None,
                  radius_m=radius,version=revision+1,record_id=identity,replace_single_event=event['id'] if scope=='place' else None)
        events=[event] if scope=='single' else [e for e in self.events.between(vehicle,0,32503680000000)['events'] if e['kind']=='charge_end']
        resolved=self._resolved(owner,vehicle,events,saved)
        simulated=dict(saved,records=[r for r in saved['records'] if r['id']!=identity]+[dict(id=identity,body=body,deleted=False,updated_at=int(time.time()*1000))])
        after=self._resolved(owner,vehicle,events,simulated);affected=[];fingerprints=[]
        for e in events:
            r,new=resolved[e['id']],after[e['id']]
            if scope=='place' and new.get('correction_id')!=identity and r.get('correction_id')!=identity:continue
            affected.append(dict(id=e['id'],end_time=e['end_time'],date=date_label(e['end_time']),previous_name=r['name'],previous_station=r['station_name'],
                                 new_name=new['name'],new_station=new['station_name'],effect='apply' if new.get('correction_id')==identity else 'outside_new_range'))
            fingerprints.append(dict(event=e,before=self._public(r,saved),after=self._public(new,saved)))
        if not affected:raise ValueError('没有可修改的充电记录，请调整范围后重试。')
        revisions=self.store.revisions(owner,vehicle,(COLLECTION,'place_names'),include_commute=True)
        digest=dict(owner=owner,vehicle=vehicle,proposal=body,revision=revisions,evidence=fingerprints)
        return body,affected,digest

    def _token(self,digest,issued):
        encoded=json.dumps([issued,digest],sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
        return str(issued)+':'+hmac.new(self.secret,encoded,hashlib.sha256).hexdigest()

    def preview(self,owner,vehicle,data):
        body,affected,digest=self._proposal(owner,vehicle,data)
        return dict(token=self._token(digest,int(time.time())),affected=affected,affected_count=len(affected),scope=body['scope'],
                    name=body['name'],station_name=body['station_name'],location=coordinates(body['point']),radius_m=body['radius_m'],revision=data['revision'])

    def _write(self,owner,vehicle,action,identity,body,revision,guard,commit_lock):
        with commit_lock if commit_lock is not None else nullcontext():
            if guard:guard()
            result=self.store.change(owner,vehicle,COLLECTION,action,identity,body,revision,guard=guard)
            return dict(revision=result['revision'],can_undo=result['can_undo'])

    def update(self,owner,vehicle,data,guard=None,commit_lock=None):
        action=data.get('action')
        if action=='preview':
            result=self.preview(owner,vehicle,data)
            if guard:guard()
            return result
        if action=='undo':return self._write(owner,vehicle,'undo',None,None,data.get('revision'),guard,commit_lock)
        if action!='save':raise ValueError('地点操作无效。')
        token=data.get('token','')
        try:issued=int(token.split(':')[0])
        except (ValueError,AttributeError):raise ValueError('请先预览地点修改。') from None
        if not 0<=time.time()-issued<=300:raise ValueError('地点预览已过期，请重新预览。')
        body,affected,digest=self._proposal(owner,vehicle,data)
        if not hmac.compare_digest(token,self._token(digest,issued)):raise ValueError('地点或记录已变化，请重新预览。')
        def write_guard():
            if guard:guard()
            if not 0<=time.time()-issued<=300:
                raise ValueError('地点预览已过期，请重新预览。')
        return self._write(owner,vehicle,'save',body['record_id'],body,data['revision'],write_guard,commit_lock)

    def candidates(self,owner,vehicle,identity,provider):
        detail=self.detail(owner,vehicle,identity);location=detail['location']
        if location is None:return dict(status='no_location',candidates=[])
        try:rows=provider.charging_candidates(dict(location,valid=True,trusted=True,coordinate_system='WGS84（社区解释）'))
        except Exception:return dict(status='unavailable',candidates=[])
        return dict(status='ok' if rows is not None else 'unavailable',candidates=rows or [])
