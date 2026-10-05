"""Offline OSM JSON -> immutable regional SQLite roads; standard library only."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile

from .road_matching_core import EARTH

DRIVING = {'motorway','trunk','primary','secondary','tertiary','unclassified',
           'residential','living_street','service','road',
           'motorway_link','trunk_link','primary_link','secondary_link','tertiary_link'}


def build_network(data, destination):
    """Atomic replacement leaves an in-flight reader on its previous snapshot."""
    nodes = {e['id']: (e['lon'], e['lat']) for e in data['elements'] if e.get('type') == 'node'
             and type(e.get('lon')) in (int,float) and type(e.get('lat')) in (int,float)
             and math.isfinite(e['lon']) and math.isfinite(e['lat'])
             and -180 <= e['lon'] <= 180 and -85 <= e['lat'] <= 85}
    ways = [e for e in data['elements'] if e.get('type') == 'way'
            and e.get('tags',{}).get('highway') in DRIVING
            and e.get('tags',{}).get('motor_vehicle') != 'no'
            and e.get('tags',{}).get('motorcar') != 'no'
            and e.get('tags',{}).get('access') != 'no']
    if not nodes or not ways:
        raise ValueError('OSM 文件没有可用的车辆道路')
    uses = Counter(n for w in ways for n in set(w['nodes']))
    lon0 = sum(p[0] for p in nodes.values())/len(nodes)
    lat0 = sum(p[1] for p in nodes.values())/len(nodes)
    scale = EARTH*math.cos(math.radians(lat0))*math.pi/180
    yscale = EARTH*math.pi/180
    destination = Path(destination)
    destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if destination.is_symlink() or destination.parent.is_symlink():
        raise ValueError('路网路径不可使用符号链接')
    fd, temporary = tempfile.mkstemp(prefix='.roads-',dir=destination.parent)
    os.close(fd)
    try:
        with sqlite3.connect(temporary) as db:
            db.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE roads(id INTEGER PRIMARY KEY,f INTEGER,t INTEGER,dir INTEGER,
                    name TEXT,length REAL,coords TEXT);
                CREATE VIRTUAL TABLE road_index USING rtree(id,minx,maxx,miny,maxy);''')
            sha = hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
            db.executemany('INSERT INTO meta VALUES (?,?)',[
                ('lon0',str(lon0)),('lat0',str(lat0)),('source_sha256',sha),
                ('attribution','© OpenStreetMap contributors; ODbL 1.0'),('schema_version','1')])
            edge = 0
            for w in ways:
                ns, tags = w['nodes'],w.get('tags',{})
                one = tags.get('oneway')
                direction = (-1 if one == '-1' else 1 if one in ('yes','1','true')
                    or (tags.get('junction') == 'roundabout' and one not in ('no','0','false')) else 0)
                start = 0
                for j in range(1,len(ns)):
                    if j == len(ns)-1 or uses[ns[j]] > 1 or (ns[0] == ns[-1] and j == len(ns)//2):
                        part, start = ns[start:j+1],j
                        if part[0] == part[-1] or any(n not in nodes for n in part):
                            continue
                        coords = [((nodes[n][0]-lon0)*scale,(nodes[n][1]-lat0)*yscale) for n in part]
                        length = sum(math.dist(a,b) for a,b in zip(coords,coords[1:]))
                        if length <= 0:
                            continue
                        edge += 1
                        db.execute('INSERT INTO roads VALUES (?,?,?,?,?,?,?)',
                            (edge,part[0],part[-1],direction,tags.get('name',''),length,json.dumps(coords)))
                        xs,ys = zip(*coords)
                        db.execute('INSERT INTO road_index VALUES (?,?,?,?,?)',
                            (edge,min(xs),max(xs),min(ys),max(ys)))
            if not edge:
                raise ValueError('OSM 文件没有可连接的车辆道路')
        os.replace(temporary,destination)
        return edge
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--osm',required=True,help='离线 Overpass OSM JSON 文件')
    parser.add_argument('--out',required=True,help='输出 region.sqlite3')
    args = parser.parse_args()
    source = Path(args.osm)
    if source.stat().st_size > 100*1024*1024:
        parser.error('区域输入超过100MB，请分区建库')
    count = build_network(json.loads(source.read_text()),args.out)
    print('Roads:',count)

if __name__ == '__main__':
    main()
