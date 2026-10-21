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
        self.addresses={}
        with UsageEvents(database).connect() as db:
            self.has_observations=db is not None and bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='observations'").fetchone())
            if db is not None:
                if history is None:history=UsageEvents(database).between(vehicle,0,32503680000001)['events']
                self.addresses=cached_names(db,vehicle,history)

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
            elif self.names and self.has_observations:
                reference=parking_place_reference(db,self.vehicle,event,self.names,self.owner,self.regions,self.rule)
                if reference:
                    point,evidence=reference;confidence='reference';reason=None
        else:
            reason='有移动或位置冲突证据，不能确认整段停车地点'
        places={side:self.interpreter._interpret(self.owner,self.vehicle,point,identity,side,self.corrections,aliases) for side in ('start','end')}
        return dict(record_id=identity,confidence=confidence,reason=reason,evidence=evidence,
                    position=position,start_place=places['start'],end_place=places['end'])
