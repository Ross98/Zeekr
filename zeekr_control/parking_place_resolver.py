"""Single interpretation entry for every saved-parking consumer."""
from .commute_tags import CommuteTags, _distance
from .geocoding import is_trusted_location
from .parking_place_reference import parking_place_reference
from .trip_place_names import TripPlaceNames, cached_names
from .trip_endpoints import endpoint
from .usage_events import UsageEvents


class ParkingPlaceResolver:
    def __init__(self, database, store, owner, vehicle, history=None):
        # Import lazily: DailyTimeline also consumes ParkingAnalytics. These are
        # existing correction/name helpers, not another parking decision path.
        from .daily_timeline import DailyTimeline, digest
        self.interpreter=DailyTimeline(database,None,store)
        self.digest=digest
        self.vehicle=vehicle
        self.owner=owner
        self.names=TripPlaceNames(store) if store else None
        self.regions=self.names.regions(owner,vehicle) if self.names else []
        self.rule=CommuteTags(store,database).rule(owner,vehicle) if store else dict(deleted=True)
        self.corrections=store.read(owner,vehicle,'place_corrections') if store else dict(records=[])
        self.corrections['_regions']=self.regions
        self.addresses={};self.charge_confirmations=[];self.arrival_confirmations=[]
        with UsageEvents(database).connect() as db:
            self.has_observations=db is not None and bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='observations'").fetchone())
            if db is not None:
                if history is None:history=UsageEvents(database).between(vehicle,0,32503680000001)['events']
                self.addresses=cached_names(db,vehicle,history)
        if store and history:
            from .charging_places import ChargingPlaces
            for record in self.corrections['records']:
                body=record['body']
                if record['deleted'] or body.get('label_only') is not True or body.get('action')!='assign' or body.get('side')!='end':continue
                trip=next((e for e in history if e['id']==body['record_id'] and e['kind']=='trip_end'),None)
                region=next((r for r in self.regions if r['id']==body.get('target_key')),None)
                if trip and region:self.arrival_confirmations.append((trip,region))
            charges=[e for e in history if e['kind']=='charge_end']
            confirmed=ChargingPlaces(database,store)._resolved(owner,vehicle,charges)
            for event in charges:
                result=confirmed.get(event['id'])
                matches=[r for r in self.regions if result and result['name_source']=='manual' and r['body']['name']==result['name']]
                if len(matches)==1:self.charge_confirmations.append((event,matches[0]))

    def record_id(self, identity):
        return 'parking_'+self.digest(identity)[:32]

    def _name(self, position):
        lat,lon=position['latitude'],position['longitude']
        place=dict(id='parking',latitude=lat,longitude=lon,label='未命名地点',name_source='reference')
        nearest=min(((_distance((lat,lon),value['point']),value['label']) for value in self.addresses.values()),default=None)
        if nearest and nearest[0]<=150:
            place.update(address_label=nearest[1],label=nearest[1],name_source='address')
        if self.names:
            place=self.names.apply(self.owner,self.vehicle,dict(places=[place]),self.rule)['places'][0]
            if place.get('manual_name_id') and place.get('name_shape')!='polygon':
                region=next(r for r in self.regions if r['id']==place['manual_name_id'])
                place.update(latitude=region['body']['latitude'],longitude=region['body']['longitude'])
        return place

    def resolve(self, db, event, fragments=()):
        start,end=event['start_time'],event['end_time']
        identity=self.record_id(event['id'])
        aliases=[self.record_id(f['id']) for f in fragments if f['start_time']>=start and f['end_time']<=end]
        point=position=evidence=None
        confidence='unknown'
        reason='停车期间没有可信定位，且未通过统一的地点推定校验'
        if not set(event.get('reasons',())) & {'movement','location'}:
            match=endpoint(db,self.vehicle,start,min(end,start+180000),True) if self.has_observations and db is not None else None
            if match:
                position=dict(latitude=match[1][0],longitude=match[1][1],state_time=match[0])
            else:
                archived=event.get('_location')
                stamp=archived.get('state_time') if isinstance(archived,dict) else None
                if (is_trusted_location(archived) and archived.get('coordinate_system')=='WGS84（社区解释）'
                        and type(stamp) in (int,float) and start<=stamp<=min(end,start+180000)):
                    position=dict(latitude=archived['latitude'],longitude=archived['longitude'],state_time=stamp)
            if position:
                point=self._name(position);confidence='observed';reason=None
            elif (event.get('parking_status')=='parked' and (event.get('p_gear_samples') or 0)>=2 and
                  any(e['end_time']==start for e,r in self.arrival_confirmations)):
                matches=[(e,r) for e,r in self.arrival_confirmations if e['end_time']==start]
                if len({r['id'] for e,r in matches})==1:
                    trip,region=matches[0];body=region['body']
                    point=dict(latitude=body['latitude'],longitude=body['longitude'],label=body['name'],name_source='manual',statistics_key='region:'+region['id'])
                    evidence=dict(source='parking_arrival_confirmation',event_id=trip['id'])
                    confidence='reference';reason=None
            elif self.names and self.has_observations:
                candidates=[(r,e['id']) for e,r in self.charge_confirmations if e.get('start_time') is not None and start<=e['start_time']<e['end_time']<=end]
                confirmed=candidates[0] if candidates and len({r['id'] for r,_ in candidates})==1 else None
                reference=parking_place_reference(db,self.vehicle,event,self.names,self.owner,self.regions,self.rule,confirmed_region=confirmed)
                if reference:
                    point,evidence=reference;confidence='reference';reason=None
        else:
            reason='有移动或位置冲突证据，不能确认整段停车地点'
        places={side:self.interpreter._interpret(self.owner,self.vehicle,point,identity,side,self.corrections,aliases) for side in ('start','end')}
        return dict(record_id=identity,confidence=confidence,reason=reason,evidence=evidence,
                    position=position,start_place=places['start'],end_place=places['end'])
