"""Isolated, bounded offline road matching. Only JSON via private stdin/stdout."""
import json
import math
import os
import resource
from pathlib import Path
import sqlite3
import sys

from .road_matching_core import EARTH, RoadGraph, match


def choose_network(paths, points):
    """Pick one connected regional graph, using cheap spatial-index hit counts."""
    ranked = []
    for path in paths:
        with sqlite3.connect(Path(path).absolute().as_uri()+'?mode=ro',uri=True) as db:
            meta = dict(db.execute('SELECT key,value FROM meta'))
            lon0,lat0 = float(meta['lon0']),float(meta['lat0'])
            scale = EARTH*math.cos(math.radians(lat0))*math.pi/180
            yscale = EARTH*math.pi/180
            hits = 0
            for p in points:
                x,y = (p[1]-lon0)*scale,(p[2]-lat0)*yscale
                hits += db.execute('SELECT 1 FROM road_index WHERE maxx>=? AND minx<=? '
                    'AND maxy>=? AND miny<=? LIMIT 1',(x-50,x+50,y-50,y+50)).fetchone() is not None
            if hits:
                ranked.append((hits,-Path(path).stat().st_size,path))
    return max(ranked)[2] if ranked else None


def process(payload):
    lines,spans,matched,issues,total = [],[],[],0,0
    for fragment in payload['fragments']:
        points,indices = fragment['points'],fragment['indices']
        total += len(points)
        path = choose_network(payload['networks'],points)
        if path is None:
            continue
        graph = RoadGraph(path)
        try:
            result = match(graph,points)
            lines.extend(result['lines'])
            spans.extend([[indices[a],indices[b]] for a,b in result['spans']])
            matched.extend(indices[i] for i in result['matched_seq'])
            issues += result['issues']
        finally:
            graph.db.close()
            graph.edge.cache_clear()
    count = sum(len(line) for line in lines)
    if count > 40000:
        return dict(status='limit',lines=[],spans=[],matched_indices=[],issues=0)
    status = 'matched' if len(matched) == total and issues == 0 else 'partial' if matched else 'unmatched'
    return dict(status=status,lines=lines,spans=spans,matched_indices=sorted(set(matched)),issues=issues)


def main():
    # Set limits after exec: preexec_fn is unsafe in the threaded web process.
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_CPU,(6,6))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS,(256*1024*1024,256*1024*1024))
    payload = json.loads(sys.stdin.read(2*1024*1024))
    encoded = json.dumps(process(payload),allow_nan=False)
    if len(encoded) > 1500000:
        encoded = json.dumps(dict(status='limit',lines=[],spans=[],matched_indices=[],issues=0))
    sys.stdout.write(encoded)

if __name__ == '__main__':
    main()
