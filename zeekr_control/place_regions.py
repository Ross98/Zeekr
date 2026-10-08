"""Shared circle/polygon membership for saved, owner-scoped place regions."""
from collections import defaultdict
import math

from .commute_tags import _distance
from .trip_place_geometry import cell, NEIGHBOURS

MAX_VERTICES = 100
EPSILON = 1e-9


def _xy(point, origin):
    return (((point[1]-origin[1]+180) % 360)-180, point[0]-origin[0])


def _on_segment(point, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = math.hypot(dx, dy)
    if not length:
        return math.dist(point, a) <= EPSILON
    cross = abs(dx*(point[1]-a[1])-dy*(point[0]-a[0]))
    return (cross <= EPSILON*length and
            min(a[0],b[0])-EPSILON <= point[0] <= max(a[0],b[0])+EPSILON and
            min(a[1],b[1])-EPSILON <= point[1] <= max(a[1],b[1])+EPSILON)


def _edges(vertices):
    return list(zip(vertices, vertices[1:]+vertices[:1]))


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _intersects(a, b, c, d):
    if any(_on_segment(p, x, y) for p,x,y in ((a,c,d),(b,c,d),(c,a,b),(d,a,b))):
        return True
    return _cross(a,b,c)*_cross(a,b,d) < 0 and _cross(c,d,a)*_cross(c,d,b) < 0


def validate_polygon(vertices):
    if not isinstance(vertices, list) or not 3 <= len(vertices) <= MAX_VERTICES:
        raise ValueError('多边形需包含 3–100 个顶点。')
    clean=[]
    for point in vertices:
        if (not isinstance(point,(list,tuple)) or len(point)!=2 or
                any(type(v) not in (int,float) or not math.isfinite(v) for v in point) or
                not -90 < point[0] < 90 or not -180 <= point[1] <= 180):
            raise ValueError('多边形顶点坐标无效。')
        clean.append([float(point[0]),float(point[1])])
    if clean[0]==clean[-1]:clean.pop()
    if len(clean)<3 or len({tuple(p) for p in clean})!=len(clean):
        raise ValueError('多边形需至少三个不同顶点，不能重复顶点。')
    projected=[_xy(p,clean[0]) for p in clean]
    edges=_edges(projected)
    for i,(a,b) in enumerate(edges):
        for j,(c,d) in enumerate(edges[i+1:],i+1):
            if j==i+1 or i==0 and j==len(edges)-1:continue
            if _intersects(a,b,c,d):raise ValueError('多边形边界不能自交或相互接触。')
    area=abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in edges))
    if area <= EPSILON**2:raise ValueError('多边形必须围成有效区域，不能共线。')
    return clean


def contains(body, point):
    if body.get('shape')!='polygon':
        return _distance(point,(body['latitude'],body['longitude'])) <= body.get('radius_m',150)+1e-7
    vertices=body['vertices'];origin=vertices[0]
    p=_xy(point,origin);ring=[_xy(v,origin) for v in vertices]
    if (p[0]<min(v[0] for v in ring)-EPSILON or p[0]>max(v[0] for v in ring)+EPSILON or
            p[1]<min(v[1] for v in ring)-EPSILON or p[1]>max(v[1] for v in ring)+EPSILON):
        return False
    inside=False
    for a,b in _edges(ring):
        if _on_segment(p,a,b):return True
        if (a[1]>p[1]) != (b[1]>p[1]):
            x=a[0]+(p[1]-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if p[0]<x:inside=not inside
    return inside


def overlaps(first, second):
    a,b=first.get('shape')=='polygon',second.get('shape')=='polygon'
    if not a and not b:
        return _distance((first['latitude'],first['longitude']),(second['latitude'],second['longitude'])) <= first.get('radius_m',150)+second.get('radius_m',150)
    if not a:return overlaps(second,first)
    if b:
        if any(contains(first,p) for p in second['vertices']) or any(contains(second,p) for p in first['vertices']):return True
        origin=first['vertices'][0]
        edges1=_edges([_xy(p,origin) for p in first['vertices']])
        edges2=_edges([_xy(p,origin) for p in second['vertices']])
        return any(_intersects(x,y,u,v) for x,y in edges1 for u,v in edges2)
    center=(second['latitude'],second['longitude']);radius=second.get('radius_m',150)
    if contains(first,center):return True
    scale=math.pi*6371000/180
    ring=[(x*scale*math.cos(math.radians(center[0])),y*scale) for x,y in (_xy(p,center) for p in first['vertices'])]
    for x,y in _edges(ring):
        dx,dy=y[0]-x[0],y[1]-x[1];length=dx*dx+dy*dy
        fraction=max(0,min(1,-(x[0]*dx+x[1]*dy)/length)) if length else 0
        if math.hypot(x[0]+fraction*dx,x[1]+fraction*dy)<=radius+1e-7:return True
    return False


class RegionIndex:
    """Keep legacy circle lookup bounded; polygons use exact boundary membership."""
    def __init__(self, records):
        self.circles=defaultdict(list);self.polygons=[]
        for record in records:
            if record.get('deleted'):continue
            body=record['body']
            if body.get('shape')=='polygon':self.polygons.append(record)
            else:self.circles[cell((body['latitude'],body['longitude']))].append(record)

    def matches(self, point):
        bucket=cell(point)
        candidates=[r for delta in NEIGHBOURS for r in self.circles.get(tuple(a+b for a,b in zip(bucket,delta)),())]+self.polygons
        return sorted((r for r in candidates if contains(r['body'],point)),
                      key=lambda r:(_distance(point,(r['body']['latitude'],r['body']['longitude'])),r.get('id','')))

    def pick(self, point):
        matches=self.matches(point)
        if len(matches)>1 and any(r['body'].get('shape')=='polygon' for r in matches):return None
        return matches[0] if matches else None
