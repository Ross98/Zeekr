"""Owner-scoped commute rules and evidence-bound endpoint matching."""
import math
import time

from .tracks import TrackStore
from .trip_endpoints import endpoint


def _point(value):
    if not isinstance(value, dict):
        raise ValueError('请在地图上选择有效地点。')
    lat, lon, radius = (value.get(key) for key in ('latitude', 'longitude', 'radius_m'))
    if (type(lat) not in (int, float) or type(lon) not in (int, float)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180
            or (lat == 0 and lon == 0) or type(radius) is not int or not 100 <= radius <= 1000):
        raise ValueError('地点坐标或范围无效；半径须为 100–1000 米。')
    return float(lat), float(lon), radius


def _distance(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    angle = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(angle)))


class CommuteTags:
    def __init__(self, store, database):
        self.store = store
        self.tracks = TrackStore(database, readonly=True)

    @staticmethod
    def _versions(db, owner, vehicle):
        if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='commute_rule_versions'").fetchone():
            return []
        return db.execute('SELECT version,effective_at,enabled,deleted,home_lat,home_lon,home_radius,'
                          'work_lat,work_lon,work_radius FROM commute_rule_versions '
                          'WHERE owner=? AND vehicle=? ORDER BY version', (owner, vehicle)).fetchall()

    @staticmethod
    def _public(row):
        if row is None:
            return dict(revision=0, enabled=False, deleted=False, home=None, work=None)
        version, effective, enabled, deleted, a, b, r1, c, d, r2 = row
        return dict(revision=version, effective_at=effective, enabled=bool(enabled), deleted=bool(deleted),
                    home=dict(latitude=a, longitude=b, radius_m=r1) if a is not None else None,
                    work=dict(latitude=c, longitude=d, radius_m=r2) if c is not None else None)

    def rule(self, owner, vehicle):
        with self.store.connect() as db:
            rows = self._versions(db, owner, vehicle)
        return self._public(rows[-1] if rows else None)

    def update(self, owner, vehicle, data, guard=None):
        action = data.get('action')
        if action not in ('commute-save', 'commute-pause', 'commute-resume', 'commute-delete'):
            raise ValueError('通勤规则操作无效。')
        with self.store.connect(write=True) as db, db:
            db.execute('BEGIN IMMEDIATE')
            rows = self._versions(db, owner, vehicle)
            old = rows[-1] if rows else None
            revision = old[0] if old else 0
            if type(data.get('revision')) is not int or data['revision'] != revision:
                raise ValueError('通勤规则已有更新，请重新读取。')
            if action == 'commute-save':
                home, work = _point(data.get('home')), _point(data.get('work'))
                if _distance(home[:2], work[:2]) <= home[2] + work[2]:
                    raise ValueError('两个通勤范围重叠，地点过近；请调整中心或半径。')
                values = (*home, *work)
                enabled, deleted = 1, 0
            else:
                if not old or old[3]:
                    raise ValueError('请先保存通勤地点。')
                values = (*old[4:7], *old[7:10])
                enabled, deleted = (0, 1) if action == 'commute-delete' else (int(action == 'commute-resume'), 0)
            effective = max(int(time.time()*1000), old[1]+1 if old else 0)
            db.execute('INSERT INTO commute_rule_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (owner, vehicle, revision+1, effective, enabled, deleted, *values))
            if guard: guard()
            return self._public((revision+1, effective, enabled, deleted, *values))

    def exclude(self, owner, vehicle, event_id, excluded, guard=None):
        with self.store.connect(write=True) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT result FROM commute_decisions WHERE owner=? AND vehicle=? AND event_id=?',
                             (owner, vehicle, event_id)).fetchone()
            if not row or row[0] != 'matched':
                raise ValueError('这趟行程没有自动通勤标签。')
            db.execute('UPDATE commute_decisions SET excluded=? WHERE owner=? AND vehicle=? AND event_id=?',
                       (int(excluded), owner, vehicle, event_id))
            if guard: guard()

    def _endpoint(self, vehicle, start, end, near_start):
        if not self.tracks.path.exists():
            return None
        lower, upper = (start, min(start+180000,end)) if near_start else (max(start,end-180000),end)
        with self.tracks.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='observations'").fetchone():
                return None
            return endpoint(db, vehicle, lower, upper, near_start)

    def _match(self, vehicle, event, rule):
        start, end = event['start_time'], event['end_time']
        if type(start) not in (int,float) or type(end) not in (int,float) or end <= start:
            return ('insufficient', None, None, None, None)
        first, last = self._endpoint(vehicle,start,end,True), self._endpoint(vehicle,start,end,False)
        if first is None or last is None or first[0] == last[0]:
            return ('insufficient', first[0] if first else None,last[0] if last else None,None,None)
        home, work = (rule[4:6], rule[7:9])
        a_home, a_work = _distance(first[1],home), _distance(first[1],work)
        b_home, b_work = _distance(last[1],home), _distance(last[1],work)
        outward = a_home <= rule[6] and b_work <= rule[9]
        backward = a_work <= rule[9] and b_home <= rule[6]
        distances = (a_home,b_work) if outward or not backward else (a_work,b_home)
        return ('matched' if outward or backward else 'outside',first[0],last[0],*distances)

    def decisions(self, owner, vehicle, events, guard=None):
        with self.store.connect() as db:
            versions = self._versions(db, owner, vehicle)
            found = {}
            if db is not None and versions:
                for event in events:
                    row = db.execute('SELECT result,excluded FROM commute_decisions '
                                     'WHERE owner=? AND vehicle=? AND event_id=?',
                                     (owner,vehicle,event['id'])).fetchone()
                    if row: found[event['id']] = row
        for event in events:
            if event['id'] in found:
                continue
            rule = next((row for row in reversed(versions) if event['end_time'] > row[1]),None)
            if rule is None or not rule[2] or rule[3]:
                continue
            result = self._match(vehicle,event,rule)
            with self.store.connect(write=True) as db, db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT OR IGNORE INTO commute_decisions VALUES(?,?,?,?,?,?,?,?,?,0)',
                           (owner,vehicle,event['id'],rule[0],*result))
                if guard: guard()
                found[event['id']] = db.execute('SELECT result,excluded FROM commute_decisions '
                    'WHERE owner=? AND vehicle=? AND event_id=?',(owner,vehicle,event['id'])).fetchone()
        return found
