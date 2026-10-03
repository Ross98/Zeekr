"""Monthly reference places from trusted observations; no event/location writes."""
from collections import Counter, defaultdict

from .commute_tags import _distance
from .tracks import TrackStore
from .trip_endpoints import endpoint
from .trip_place_names import cached_names

from .trip_place_geometry import RADIUS_M, cell, NEIGHBOURS


def cluster_endpoints(rows, regions=()):
    """Fixed chronological anchors, nearest matching centre, no transitive chaining."""
    places, centers, buckets, assignments = [], [], defaultdict(list), {}
    names=defaultdict(list)
    for record in regions:
        body=record['body'];names[cell((body['latitude'],body['longitude']))].append(record)
    for row in sorted(rows, key=lambda r: (r['time'], r['event_id'], r['side'])):
        point, key = row['point'], cell(row['point'])
        candidates=[r for delta in NEIGHBOURS for r in names.get(tuple(a+b for a,b in zip(key,delta)),())]
        candidates=sorted((_distance(point,(r['body']['latitude'],r['body']['longitude'])),r['id'],r)
                          for r in candidates if _distance(point,(r['body']['latitude'],r['body']['longitude']))<=r['body'].get('radius_m',RADIUS_M)+1e-7)
        region=candidates[0][2] if candidates else None
        region_id=region['id'] if region else None
        nearby = [index for delta in NEIGHBOURS
                  for index in buckets.get(tuple(a+b for a,b in zip(key,delta)),())]
        matches = sorted((_distance(point, centers[i]), i) for i in nearby if places[i].get('name_region_id')==region_id)
        if matches and matches[0][0] <= RADIUS_M + 1e-7:
            index = matches[0][1]
        else:
            index = len(places)
            center=(region['body']['latitude'],region['body']['longitude']) if region else point
            centers.append(center); buckets[cell(center)].append(index)
            places.append(dict(id='place_'+str(index+1), label='参考地点 '+str(index+1),
                               latitude=center[0], longitude=center[1], departures=0, arrivals=0,
                               name_region_id=region_id))
        place = places[index]
        place['departures' if row['side']=='start' else 'arrivals'] += 1
        assignments.setdefault(row['event_id'], dict(start=None,end=None))[row['side']] = place['id']
    return dict(places=places, assignments=assignments)


class TripPlaces:
    def __init__(self, database):
        self.tracks = TrackStore(database, readonly=True)

    def query(self, vehicle, events, regions=(), include_samples=False):
        observations = [];addresses={}
        if events and self.tracks.path.exists():
            with self.tracks.connect() as db:
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='observations'").fetchone()
                if exists:
                    addresses=cached_names(db,vehicle,events)
                    for event in events:
                        start, end = event['start_time'], event['end_time']
                        ordered = start is not None and end > start
                        first = endpoint(db,vehicle,start,min(start+180000,end),True) if ordered else None
                        last = endpoint(db,vehicle,max(start if ordered else 0,end-180000),end,False) if start is None or ordered else None
                        # A single shared sample cannot establish both boundaries.
                        if first and last and first[0] == last[0]:
                            first = last = None
                        for side, sample in (('start',first),('end',last)):
                            if sample:
                                observations.append(dict(event_id=event['id'],side=side,time=sample[0],point=sample[1]))
        result = cluster_endpoints(observations,regions)
        assignments = result.pop('assignments')
        votes=defaultdict(Counter)
        by_id={p['id']:p for p in result['places']}
        for sample in observations:
            candidate=addresses.get((sample['event_id'],sample['side']))
            place_id=assignments[sample['event_id']][sample['side']];place=by_id[place_id]
            if candidate and _distance(sample['point'],candidate['point'])<=RADIUS_M and _distance((place['latitude'],place['longitude']),candidate['point'])<=RADIUS_M:
                votes[place_id][candidate['label']]+=1
        for place_id,counts in votes.items():
            ranked=counts.most_common()
            if len(ranked)==1 or ranked[0][1]>ranked[1][1]:by_id[place_id]['address_label']=ranked[0][0]
        routes = Counter()
        unknown = Counter()
        for event in events:
            pair = assignments.get(event['id'], dict(start=None,end=None))
            event['start_place'], event['end_place'] = pair['start'], pair['end']
            for side in ('start','end'):
                if pair[side] is None: unknown[side] += 1
            if pair['start'] and pair['end']:
                routes[(pair['start'],pair['end'])] += 1
        if include_samples:result['_endpoints']=observations
        return dict(result,radius_m=RADIUS_M,unknown_departures=unknown['start'],unknown_arrivals=unknown['end'],
                    routes=[dict(start_place=a,end_place=b,count=count)
                            for (a,b),count in sorted(routes.items(),key=lambda item:(-item[1],item[0]))])
