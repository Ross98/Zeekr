"""Road matching runtime: Python standard library only, immutable SQLite road data."""
import math, sqlite3, json, heapq, functools
EARTH = 6371008.8

def project_point(point, line):
    best = (float('inf'), 0.0, line[0])
    offset = 0.0
    for a, b in zip(line, line[1:]):
        dx, dy = (b[0] - a[0], b[1] - a[1])
        length = math.hypot(dx, dy)
        t = max(0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (length * length))) if length else 0
        q = (a[0] + t * dx, a[1] + t * dy)
        dist = math.hypot(point[0] - q[0], point[1] - q[1])
        if dist < best[0]:
            best = (dist, offset + t * length, q)
        offset += length
    return best

def clip_line(line, start, end):
    if end < start:
        return list(reversed(clip_line(line, end, start)))
    out = []
    offset = 0.0
    for a, b in zip(line, line[1:]):
        length = math.dist(a, b)
        if length and offset + length >= start and (offset <= end):
            lo = max(0, min(1, (start - offset) / length))
            hi = max(0, min(1, (end - offset) / length))
            for t in (lo, hi):
                q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
                if not out or math.dist(q, out[-1]) > 1e-08:
                    out.append(q)
        offset += length
    return out

def split_on_gaps(ids, points):
    result = []
    for i in ids:
        if not result or points[i][0] - points[result[-1][-1]][0] > 180000:
            result.append([])
        result[-1].append(i)
    return result

class RoadGraph:

    def __init__(self, path):
        self.db = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)
        meta = dict(self.db.execute('select key,value from meta'))
        self.lon0 = float(meta['lon0'])
        self.lat0 = float(meta['lat0'])
        self.scale = EARTH * math.cos(math.radians(self.lat0)) * math.pi / 180
        self.yscale = EARTH * math.pi / 180
        self.adj = {}
        self.route_cache = {}
        self.cache_limit = 24
        for edge, f, t, direction, length in self.db.execute('select id,f,t,dir,length from roads'):
            if direction != -1:
                self.adj.setdefault(f, []).append((t, length, edge, False))
            if direction != 1:
                self.adj.setdefault(t, []).append((f, length, edge, True))

    def xy(self, p):
        return ((p[0] - self.lon0) * self.scale, (p[1] - self.lat0) * self.yscale)

    def lnglat(self, p):
        return (p[0] / self.scale + self.lon0, p[1] / self.yscale + self.lat0)

    @functools.lru_cache(maxsize=256)
    def edge(self, edge):
        f, t, d, l, coords = self.db.execute('select f,t,dir,length,coords from roads where id=?', (edge,)).fetchone()
        return (f, t, d, l, [tuple(p) for p in json.loads(coords)])

    def candidates(self, p, index):
        x, y = self.xy((p[1], p[2]))
        cs = []
        ids = self.db.execute('select id from road_index where maxx>=? and minx<=? and maxy>=? and miny<=?', (x - 50, x + 50, y - 50, y + 50))
        for edge, in ids:
            f, t, d, length, line = self.edge(edge)
            error, pos, snap = project_point((x, y), line)
            if error > 50:
                continue
            for rev in [False] if d == 1 else [True] if d == -1 else [False, True]:
                cs.append(dict(id=edge, u=t if rev else f, v=f if rev else t, reverse=rev, length=length, pos=length - pos if rev else pos, error=error, obs=index, snap=snap))
        return sorted(cs, key=lambda c: (c['error'], c['id'], c['reverse']))[:12]

    def route(self, start, target):
        if start == target:
            return (0.0, [])
        if start in self.route_cache:
            distances, parents = self.route_cache.pop(start)
            self.route_cache[start] = (distances, parents)
        else:
            distances = {start: 0.0}
            parents = {}
            queue = [(0.0, start)]
            while queue:
                cost, node = heapq.heappop(queue)
                if cost != distances[node]:
                    continue
                for nxt, length, edge, rev in self.adj.get(node, []):
                    new = cost + length
                    if new <= 10000 and new < distances.get(nxt, float('inf')):
                        distances[nxt] = new
                        parents[nxt] = (node, edge, rev)
                        heapq.heappush(queue, (new, nxt))
            self.route_cache[start] = (distances, parents)
            if len(self.route_cache) > self.cache_limit:
                del self.route_cache[next(iter(self.route_cache))]
        if target not in distances:
            return (float('inf'), [])
        path = []
        node = target
        while node != start:
            node, edge, rev = parents[node]
            path.append((edge, rev))
        return (distances[target], list(reversed(path)))

    def transition(self, a, b):
        if (a['id'], a['reverse']) == (b['id'], b['reverse']) and b['pos'] >= a['pos'] - 20:
            return (abs(b['pos'] - a['pos']), [])
        distance, path = self.route(a['v'], b['u'])
        return (a['length'] - a['pos'] + distance + b['pos'], path)

    def oriented(self, c):
        line = self.edge(c['id'])[4]
        return list(reversed(line)) if c['reverse'] else line

    def pieces(self, a, b):
        distance, path = self.transition(a, b)
        if not math.isfinite(distance):
            return []
        if (a['id'], a['reverse']) == (b['id'], b['reverse']) and b['pos'] >= a['pos'] - 20:
            return [clip_line(self.oriented(a), a['pos'], b['pos'])]
        out = [clip_line(self.oriented(a), a['pos'], a['length'])]
        for edge, rev in path:
            line = self.edge(edge)[4]
            out.append(list(reversed(line)) if rev else line)
        out.append(clip_line(self.oriented(b), 0, b['pos']))
        return out

def match(graph, points):
    """Nearest road, with continuity checks before accepting directed detours."""
    candidates = {i: cs for i, p in enumerate(points) if (cs := graph.candidates(p, i))}
    groups = split_on_gaps(list(candidates), points)
    lines, chosen, spans, issues = ([], [], [], 0)
    def direct(a,b):
        return math.dist(graph.xy(points[a['obs']][1:]),graph.xy(points[b['obs']][1:]))
    def plausible(distance,straight):
        # Not a speed estimate: reject large geometric detours unsupported by
        # these samples. Nearby parallel lanes may be closer than GPS drift.
        return math.isfinite(distance) and distance<=straight*2+200
    def score(a,b):
        return abs(graph.transition(a,b)[0]-direct(a,b))+3*(a['error']+b['error'])
    for group in groups:
        first=candidates[group[0]]
        if len(group)>1:
            second=candidates[group[1]]
            near_first=[c for c in first if c['error']<=first[0]['error']+1e-06]
            near_second=[c for c in second if c['error']<=second[0]['error']+1e-06]
            a,b=min(((a,b) for a in near_first for b in near_second),key=lambda pair:score(*pair))
            if not plausible(graph.transition(a,b)[0],direct(a,b)):
                a,b=min(((a,b) for a in first for b in second),key=lambda pair:score(*pair))
            picks=[a,b]
        else:
            picks=[first[0]]
        for i in group[len(picks):]:
            cs = candidates[i]
            nearest = cs[0]['error']
            a=picks[-1]
            best=min((c for c in cs if c['error']<=nearest+1e-06),key=lambda c:score(a,c))
            if not plausible(graph.transition(a,best)[0],direct(a,best)):
                best=min(cs,key=lambda c:score(a,c))
            picks.append(best)
        chosen.extend(picks)
        for a, b in zip(picks, picks[1:]):
            if not plausible(graph.transition(a,b)[0],direct(a,b)):
                issues+=1
                continue
            pieces = [line for line in graph.pieces(a, b) if len(line) >= 2 and math.dist(line[0], line[-1]) > 1e-08]
            if pieces:
                spans.append([a['obs'], b['obs']])
                lines.extend([list(map(graph.lnglat, line)) for line in pieces])
            elif math.dist(a['snap'], b['snap']) > 1e-06:
                issues += 1
            else:
                spans.append([a['obs'], b['obs']])
    return dict(lines=lines, spans=spans, matched_seq=[c['obs'] for c in chosen], matched=len(chosen), total=len(points), issues=issues)
