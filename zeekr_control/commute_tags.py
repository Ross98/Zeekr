"""Owner-scoped commute rules and evidence-bound endpoint matching."""
import math
import hashlib
import json
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
            row = db.execute('SELECT result,excluded FROM commute_decisions WHERE owner=? AND vehicle=? AND event_id=?',
                             (owner, vehicle, event_id)).fetchone()
            if not row or (row[0] != 'matched' and not row[1]):
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

    def _evaluate(self, vehicle, event, rule):
        start, end = event['start_time'], event['end_time']
        valid = type(start) in (int, float) and type(end) in (int, float) and end > start
        first = self._endpoint(vehicle, start, end, True) if valid else None
        last = self._endpoint(vehicle, start, end, False) if valid else None
        parking = {}
        # Revalidate from the vehicle database, never trust caller-supplied place
        # labels/evidence. Keep these estimates distinct from trusted GPS samples.
        if valid and event.get('partial') is False and (first is None or last is None) and self.tracks.path.exists():
            from .parking_origin import parking_origin
            from .parking_destination import parking_destination
            with self.tracks.connect() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='observations'").fetchone():
                    for side, sample, infer in (('start', first, parking_origin), ('end', last, parking_destination)):
                        if sample is not None:
                            continue
                        estimate = infer(db, vehicle, event)
                        if estimate:
                            parking[side + '_place_evidence'] = {k: v for k, v in estimate.items() if k != 'point'}
                            sample = estimate['sample_time'], estimate['point']
                            if side == 'start': first = sample
                            else: last = sample
        signature = hashlib.sha256(json.dumps(
            [start, end, event.get('partial'), first, last, parking, list(rule)],
            separators=(',', ':')).encode()).hexdigest()
        evidence = dict(direction=None, partial=bool(event.get('partial')), rule_revision=rule[0],
                        start_distance_m=None, end_distance_m=None,
                        start_radius_m=rule[6], end_radius_m=rule[9],
                        start_sample_time=first[0] if first else None,
                        end_sample_time=last[0] if last else None, **parking)
        if event.get('partial') is not False or first is None or last is None or first[0] == last[0]:
            return ('insufficient', evidence['start_sample_time'], evidence['end_sample_time'], None, None), evidence, signature
        a_home, a_work = _distance(first[1], rule[4:6]), _distance(first[1], rule[7:9])
        b_home, b_work = _distance(last[1], rule[4:6]), _distance(last[1], rule[7:9])
        outward = a_home <= rule[6] and b_work <= rule[9]
        backward = a_work <= rule[9] and b_home <= rule[6]
        use_backward = backward or (not outward and max(a_work/rule[9], b_home/rule[6]) < max(a_home/rule[6], b_work/rule[9]))
        a, b = (a_work, b_home) if use_backward else (a_home, b_work)
        evidence.update(direction='backward' if use_backward else 'outbound',
                        start_distance_m=round(a, 1), end_distance_m=round(b, 1),
                        start_radius_m=rule[9] if use_backward else rule[6],
                        end_radius_m=rule[6] if use_backward else rule[9])
        return ('matched' if outward or backward else 'outside', first[0], last[0], a, b), evidence, signature

    def _match(self, vehicle, event, rule):
        return self._evaluate(vehicle, event, rule)[0]

    def notification_places(self, owner, vehicle, event, guard=None):
        """Project the shared commute decision as labels, never GPS coordinates."""
        if event.get('kind') != 'trip_end' or event.get('partial') is not False:
            return {}
        decision = self.decisions(owner, vehicle, [event], guard=guard).get(event['id'])
        if not decision:
            return {}
        result, excluded, evidence = decision
        if (result != 'matched' or excluded or not isinstance(evidence, dict)
                or evidence.get('legacy') or evidence.get('partial') is not False
                or evidence.get('direction') not in ('outbound', 'backward')):
            return {}
        labels = ('家', '公司') if evidence['direction'] == 'outbound' else ('公司', '家')
        # A uniquely named region containing the configured home/work centre
        # is an explicit alias, still an inference rather than endpoint GPS.
        from .trip_place_names import TripPlaceNames
        with self.store.connect() as db:
            version=next((row for row in self._versions(db,owner,vehicle)
                          if row[0]==evidence['rule_revision']),None)
        aliases=TripPlaceNames(self.store).apply(owner,vehicle,dict(places=[]),self._public(version))
        roles=('home','work') if evidence['direction']=='outbound' else ('work','home')
        return {side: dict(name=aliases['commute_place_names'].get(role,label), reference=dict(source='commute_rule', side=side,
                    rule_revision=evidence['rule_revision'],
                    named_region_id=aliases['commute_place_regions'].get(role),
                    sample_time=evidence.get(side+'_sample_time'),
                    place_evidence=evidence.get(side+'_place_evidence')))
                for side, label, role in zip(('start', 'end'), labels, roles)}

    @staticmethod
    def _evidence(db, owner, vehicle, event_id):
        if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='commute_evidence'").fetchone():
            return None
        row = db.execute('SELECT signature,body FROM commute_evidence WHERE owner=? AND vehicle=? AND event_id=?',
                         (owner, vehicle, event_id)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    @staticmethod
    def _save(db, owner, vehicle, event_id, rule, result, evidence, signature, excluded):
        db.execute('CREATE TABLE IF NOT EXISTS commute_evidence ('
                   'owner TEXT,vehicle TEXT,event_id TEXT,signature TEXT NOT NULL,body TEXT NOT NULL,'
                   'PRIMARY KEY(owner,vehicle,event_id))')
        db.execute('INSERT OR REPLACE INTO commute_decisions VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (owner, vehicle, event_id, rule[0], *result, int(excluded)))
        db.execute('INSERT OR REPLACE INTO commute_evidence VALUES(?,?,?,?,?)',
                   (owner, vehicle, event_id, signature, json.dumps(evidence, separators=(',', ':'))))

    def decisions(self, owner, vehicle, events, guard=None):
        with self.store.connect() as db:
            versions = self._versions(db, owner, vehicle)
            found, existing, evidence_rows = {}, {}, {}
            for event in events if versions else []:
                row = db.execute('SELECT result,excluded,rule_version,start_time,end_time,start_distance,end_distance '
                                 'FROM commute_decisions WHERE owner=? AND vehicle=? AND event_id=?',
                                 (owner, vehicle, event['id'])).fetchone()
                if row:
                    existing[event['id']] = row
                    evidence_rows[event['id']] = self._evidence(db, owner, vehicle, event['id'])
        for event in events:
            old = existing.get(event['id'])
            stored = evidence_rows.get(event['id'])
            rule = (next((row for row in versions if row[0] == old[2]), None) if old else
                    next((row for row in reversed(versions) if event['end_time'] > row[1]), None))
            if rule is None or not rule[2] or rule[3]:
                continue
            if old and (old[0] == 'matched' or old[1]):
                details = stored[1] if stored else dict(direction=None, partial=bool(event.get('partial')),
                    rule_revision=rule[0], start_distance_m=old[5], end_distance_m=old[6],
                    start_sample_time=old[3], end_sample_time=old[4], legacy=True)
                found[event['id']] = (old[0], old[1], details)
                continue
            result, details, signature = self._evaluate(vehicle, event, rule)
            if old and stored and stored[0] == signature:
                found[event['id']] = (old[0], old[1], stored[1])
                continue
            with self.store.connect(write=True) as db, db:
                db.execute('BEGIN IMMEDIATE')
                # A concurrent preview application or manual exclusion wins.
                current = db.execute('SELECT result,excluded,rule_version FROM commute_decisions '
                    'WHERE owner=? AND vehicle=? AND event_id=?', (owner, vehicle, event['id'])).fetchone()
                expected = old[:3] if old else None
                current_evidence = self._evidence(db, owner, vehicle, event['id'])
                if current != expected or (current_evidence[0] if current_evidence else None) != (stored[0] if stored else None):
                    if current:
                        saved = self._evidence(db, owner, vehicle, event['id'])
                        found[event['id']] = (*current[:2], saved[1] if saved else None)
                    continue
                self._save(db, owner, vehicle, event['id'], rule, result, details, signature, False)
                if guard: guard()
                found[event['id']] = (result[0], 0, details)
        return found

    def reassess(self, owner, vehicle, events, data, guard=None):
        apply = data['action'] == 'commute-apply'
        with self.store.connect(write=apply) as db:
            if db is None:
                raise ValueError('请先保存并启用通勤规则。')
            with db:
                db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
                versions = self._versions(db, owner, vehicle)
                rule = versions[-1] if versions else None
                if not rule or not rule[2] or rule[3]:
                    raise ValueError('请先保存并启用通勤规则。')
                if type(data.get('revision')) is not int or data['revision'] != rule[0]:
                    raise ValueError('通勤规则已有变化，请重新预览。')
                if len(events) > 1000:
                    raise ValueError('本月行程超过 1000 条，暂不支持历史重判。')
                rows, candidates, counts = [], [], dict(add=0, remove=0, unchanged=0, excluded=0, insufficient=0)
                for event in events:
                    old = db.execute('SELECT result,excluded,rule_version FROM commute_decisions WHERE owner=? AND vehicle=? AND event_id=?',
                                     (owner, vehicle, event['id'])).fetchone()
                    result, evidence, signature = self._evaluate(vehicle, event, rule)
                    excluded = bool(old and old[1])
                    before, after = bool(old and old[0] == 'matched' and not excluded), result[0] == 'matched' and not excluded
                    change = 'excluded' if excluded else 'add' if after and not before else 'remove' if before and not after else 'unchanged'
                    counts[change] += 1
                    if result[0] == 'insufficient': counts['insufficient'] += 1
                    rows.append(dict(id=event['id'], start_time=event['start_time'], end_time=event['end_time'],
                                     before=before, after=after, change=change, result=result[0], **evidence))
                    candidates.append((event['id'], old, result, evidence, signature, excluded))
                token = hashlib.sha256(json.dumps([owner, vehicle, data.get('date'), list(rule), candidates],
                                        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                if apply:
                    if data.get('token') != token:
                        raise ValueError('行程、采样或标注已有变化，请重新预览。')
                    for event_id, old, result, evidence, signature, excluded in candidates:
                        self._save(db, owner, vehicle, event_id, rule, result, evidence, signature, excluded)
                    if guard: guard()
                return dict(token=token, counts=counts, rows=rows, date=data.get('date'), rule_revision=rule[0], applied=apply)

    def collect(self, owner, vehicle, now, guard=None):
        """Bound collection to the latest 100 finished trips in the last 48 hours."""
        if not self.rule(owner, vehicle)['revision']:
            return
        from .usage_events import UsageEvents, MAX_SUMMARY_BYTES, project
        from .trip_visibility import visible_clause
        source = UsageEvents(self.tracks.path)
        with source.connect() as db:
            if db is None: return
            rows = db.execute('SELECT id,summary FROM monitor_events WHERE vehicle=? AND kind=? '
                'AND created>=? AND created<=? AND length(CAST(summary AS BLOB))<=? AND ' + visible_clause(db) +
                ' ORDER BY created DESC,rowid DESC LIMIT 100',
                (vehicle, 'trip_end', now-48*3600000, now, MAX_SUMMARY_BYTES)).fetchall()
        events = []
        for identity, encoded in rows:
            try:
                event = project(identity, 'trip_end', json.loads(encoded))
            except (ValueError, TypeError):
                continue
            if event and now-48*3600000 <= event['end_time'] <= now:
                events.append(event)
        self.decisions(owner, vehicle, events, guard=guard)
