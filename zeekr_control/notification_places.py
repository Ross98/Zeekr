"""Project existing saved place labels for notifications; never repair GPS."""
from .charging_places import ChargingPlaces
from .commute_tags import CommuteTags
from .notification_location import select_location
from .trip_place_names import TripPlaceNames
from .trip_places import TripPlaces
from .usage_events import project, number


class NotificationPlaces:
    def __init__(self, database, store):
        self.names=TripPlaceNames(store)
        self.trips=TripPlaces(database)
        self.charges=ChargingPlaces(database,store)
        self.commute=CommuteTags(store,database)

    def _named(self, owner, vehicle, point, rule):
        place=dict(id='notification',latitude=point[0],longitude=point[1],label='',
                   departures=0,arrivals=0)
        place=self.names.apply(owner,vehicle,dict(places=[place]),rule)['places'][0]
        return place if place.get('name_source')=='manual' else None

    @staticmethod
    def _label(place, side, source, **evidence):
        return dict(name=place['label'],reference=dict(source='saved_place',side=side,
            region_id=place['manual_name_id'],position_source=source,**evidence))

    def resolve(self, owner, vehicle, kind, data, identity, guard=None):
        if guard:guard()
        if kind not in ('trip_start','trip_end','charge_start','charge_end'):
            return {}
        event=project(identity,kind,data)
        if kind.startswith('charge'):
            if kind=='charge_start':
                stamp=number(data.get('start_time'),1,32503680000000)
                event=dict(id=identity,kind=kind,start_time=stamp,end_time=stamp)
            if event and event.get('end_time') is not None:
                place=self.charges.notification_place(owner,vehicle,event)
                if place:
                    if guard:guard()
                    return {'start':place}
        result={}
        rule=self.commute.rule(owner,vehicle)
        with self.trips.tracks.connect() as db:
            for side in ('start','end') if kind=='trip_end' else ('start',):
                location,reference=select_location(db,vehicle,data.get(side+'_location'),data.get(side+'_time'))
                if location is None or location.get('coordinate_system')!='WGS84（社区解释）':continue
                place=self._named(owner,vehicle,(location['latitude'],location['longitude']),rule)
                if place:
                    result[side]=self._label(place,side,'historical' if reference else 'direct',
                                             position_reference=reference)
        # Exactly the same boundary selection, parking inference and naming as
        # the page; later samples are available only for finished trips.
        if kind=='trip_end' and event and len(result)<2:
            stats=self.trips.query(vehicle,[event],regions=self.names.regions(owner,vehicle),include_samples=True)
            stats=self.names.apply(owner,vehicle,stats,rule)
            places={p['id']:p for p in stats['places']}
            for sample in stats['_endpoints']:
                side=sample['side'];place=places.get(event.get(side+'_place'))
                if side in result or not place or place.get('name_source')!='manual':continue
                parking=event.get(side+'_place_evidence')
                result[side]=self._label(place,side,'parking_inferred' if parking else 'boundary_sample',
                    sample_time=sample['time'],place_evidence=parking)
        if guard:guard()
        return result
