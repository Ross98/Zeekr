"""Add inferred road geometry without changing cached source evidence."""
from collections import OrderedDict
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import threading

from .tracks import valid_timestamp

MAX_POINTS = 1500
ALGORITHM = '最近道路＋最短路径'


def drawable(point):
    return (point.get('trusted') is True and point.get('plottable') is True
        and point.get('coordinate_system') == 'WGS84（社区解释）'
        and valid_timestamp(point.get('state_time'))
        and all(type(point.get(k)) in (int,float) and math.isfinite(point[k]) and abs(point[k])<=limit
                for k,limit in [('longitude',180),('latitude',85)])
        and (point['longitude'] != 0 or point['latitude'] != 0))


def fragments(route):
    # TrackStore's trusted segments define continuity, including observed-time gaps.
    indices = {id(point):i for i,point in enumerate(route['observations'])}
    # JSON-decoded callers may not retain object identity. Match the full source record.
    values = {}
    for i,point in enumerate(route['observations']):
        values.setdefault(json.dumps(point,sort_keys=True),i)
    result = []
    for segment in route['segments']:
        current = None
        for point in segment:
            index = indices.get(id(point),values.get(json.dumps(point,sort_keys=True)))
            if index is None or not drawable(point):
                current = None
                continue
            if current and (point['state_time']<=current['points'][-1][0]
                            or point['state_time']-current['points'][-1][0]>180000
                            or index<=current['indices'][-1]):
                current = None
            if current is None:
                current = dict(points=[],indices=[])
                result.append(current)
            current['points'].append([point['state_time'],point['longitude'],point['latitude']])
            current['indices'].append(index)
    return result


class RoadMatcher:
    def __init__(self,directory):
        self.directory = Path(directory)
        self.gate = threading.BoundedSemaphore(1)
        self.lock = threading.Lock()
        self.cache = OrderedDict()

    def enrich(self,route):
        result = dict(route)
        base = dict(algorithm=ALGORITHM,coordinate_system='WGS84',inferred=True,
                    attribution='© OpenStreetMap contributors',lines=[],spans=[],matched_indices=[],issues=0)
        result['road_matching'] = base
        pieces = fragments(route)
        base['eligible_points'] = sum(len(p['points']) for p in pieces)
        if not pieces:
            base['status'] = 'empty'
            return result
        if base['eligible_points'] > MAX_POINTS:
            base['status'] = 'limit'
            return result
        try:
            networks = sorted(p for p in self.directory.glob('*.sqlite3')
                              if not p.is_symlink() and p.is_file() and p.stat().st_size<=64*1024*1024)
            if self.directory.is_symlink() or not networks:
                base['status'] = 'unavailable'
                return result
            if len(networks)>8:
                base['status'] = 'limit'
                return result
            signature = [(p.name,p.stat().st_mtime_ns,p.stat().st_size) for p in networks]
            payload = dict(networks=[str(p.absolute()) for p in networks],fragments=pieces)
            key = hashlib.sha256(json.dumps([payload,signature],sort_keys=True).encode()).hexdigest()
        except OSError:
            base['status'] = 'unavailable'
            return result
        with self.lock:
            cached = self.cache.get(key)
            if cached is not None:
                self.cache.move_to_end(key)
                base.update(copy.deepcopy(cached))
                return result
        if not self.gate.acquire(blocking=False):
            base['status'] = 'busy'
            return result
        try:
            completed = subprocess.run([sys.executable,'-m','zeekr_control.road_match_worker'],
                cwd=str(Path(__file__).parent.parent),input=json.dumps(payload),capture_output=True,
                text=True,timeout=8,check=True)
            if len(completed.stdout)>1500000:
                base['status'] = 'limit'
                return result
            output = json.loads(completed.stdout)
            if output['status'] not in ('matched','partial','unmatched','limit'):
                raise ValueError('Invalid road worker response')
            base.update(output)
            if output['status'] != 'limit':
                with self.lock:
                    self.cache[key] = copy.deepcopy(output)
                    while len(self.cache)>2:
                        self.cache.popitem(last=False)
        except subprocess.TimeoutExpired:
            base['status'] = 'timeout'
        except (subprocess.SubprocessError,OSError,ValueError,KeyError):
            # Raw worker stderr can include paths/locations. Keep diagnostics private.
            base['status'] = 'error'
        finally:
            self.gate.release()
        return result
