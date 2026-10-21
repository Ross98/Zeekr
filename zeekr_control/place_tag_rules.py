"""Versioned, owner-scoped place-to-trip labels with explicit historical application."""
import hashlib
from bisect import bisect_left
import json
import time

from .analysis_cancel import check_cancelled
from .place_regions import RegionIndex
from .trip_endpoints import endpoint
from .trip_places import cluster_endpoints
from .trip_visibility import visible_clause
from .usage_events import UsageEvents, MAX_SUMMARY_BYTES, project
from .usage_reports import period_window

MAX_TARGETS = 1000
MAX_CONTEXT = 4000
MAX_VERSIONS = 10000
MAX_PAIRS = 10000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


class PlaceTagRules:
    def __init__(self, store, database):
        self.store, self.events = store, UsageEvents(database)
        self.pending_cursor = {}

    @staticmethod
    def _exists(db):
        return db is not None and db.execute("SELECT 1 FROM sqlite_master WHERE name='place_tag_rule_versions'").fetchone()

    @staticmethod
    def _schema(db):
        db.execute('CREATE TABLE IF NOT EXISTS place_tag_rule_versions ('
                   'owner TEXT,vehicle TEXT,version INTEGER,rule_id TEXT,effective_at INTEGER,body TEXT NOT NULL,'
                   'PRIMARY KEY(owner,vehicle,version))')
        db.execute('CREATE INDEX IF NOT EXISTS place_tag_rule_identity ON place_tag_rule_versions(owner,vehicle,rule_id,version)')
        db.execute('CREATE TABLE IF NOT EXISTS place_tag_decisions ('
                   'owner TEXT,vehicle TEXT,rule_id TEXT,event_id TEXT,version INTEGER,body TEXT NOT NULL,'
                   'PRIMARY KEY(owner,vehicle,rule_id,event_id))')
        db.execute('CREATE TABLE IF NOT EXISTS place_tag_exclusions ('
                   'owner TEXT,vehicle TEXT,rule_id TEXT,event_id TEXT,excluded INTEGER NOT NULL,'
                   'PRIMARY KEY(owner,vehicle,rule_id,event_id))')
        db.execute('CREATE INDEX IF NOT EXISTS place_tag_event_decisions ON place_tag_decisions(owner,vehicle,event_id,rule_id)')
        db.execute('CREATE INDEX IF NOT EXISTS place_tag_event_exclusions ON place_tag_exclusions(owner,vehicle,event_id,rule_id)')
        db.execute("CREATE INDEX IF NOT EXISTS place_tag_pending ON place_tag_decisions(owner,vehicle,event_id) WHERE json_extract(body,'$.result')='pending'")
        db.execute('CREATE TABLE IF NOT EXISTS place_tag_decision_revisions ('
                   'owner TEXT,vehicle TEXT,revision INTEGER NOT NULL,PRIMARY KEY(owner,vehicle))')

    def _versions(self, db, owner, vehicle):
        if not self._exists(db): return []
        rows=db.execute(
            'SELECT version,rule_id,effective_at,body FROM place_tag_rule_versions '
            'WHERE owner=? AND vehicle=? ORDER BY version LIMIT ?', (owner, vehicle,MAX_VERSIONS+1)).fetchall()
        if len(rows)>MAX_VERSIONS:raise ValueError('规则版本过多，请先整理规则历史。')
        return [dict(id=i,version=v,effective_at=t,**json.loads(body)) for v,i,t,body in rows]

    def rules(self, owner, vehicle):
        self.store._key(owner, vehicle, 'tags')
        with self.store.connect() as db:
            if not self._exists(db):return dict(revision=0,decision_revision=0,rules=[])
            latest=[dict(id=i,version=v,effective_at=t,**json.loads(body)) for v,i,t,body in db.execute(
                'SELECT v.version,v.rule_id,v.effective_at,v.body FROM place_tag_rule_versions v JOIN '
                '(SELECT rule_id,MAX(version) AS version FROM place_tag_rule_versions WHERE owner=? AND vehicle=? GROUP BY rule_id) latest '
                'ON v.owner=? AND v.vehicle=? AND v.rule_id=latest.rule_id AND v.version=latest.version ORDER BY v.version',
                (owner,vehicle,owner,vehicle))]
            decision=db.execute('SELECT revision FROM place_tag_decision_revisions WHERE owner=? AND vehicle=?',(owner,vehicle)).fetchone()
        return dict(revision=max((r['version'] for r in latest),default=0),decision_revision=decision[0] if decision else 0,
                    rules=[r for r in latest if not r.get('deleted')])

    def _personal(self, db, owner, vehicle):
        saved = self.store._read(db, (owner, vehicle, 'place_names'))
        corrections = self.store._read(db, (owner, vehicle, 'place_corrections'))
        annotations = self.store._read(db, (owner, vehicle, 'tags'))
        return saved, corrections, annotations

    def _draft(self, data, saved):
        region = next((r for r in saved['records'] if not r['deleted'] and r['id']==data.get('region_id')), None)
        tag = data.get('tag')
        if region is None: raise ValueError('请选择当前车辆已保存的地点区域。')
        if not isinstance(tag, str) or not 1<=len(tag.strip())<=24 or any(ord(c)<32 for c in tag):
            raise ValueError('标签需为 1–24 字，不能含控制字符。')
        if data.get('direction') not in ('arrive','depart','either'):
            raise ValueError('请选择到达、出发或双向。')
        if type(data.get('require_charge')) is not bool or type(data.get('enabled')) is not bool:
            raise ValueError('规则开关或充电条件无效。')
        return dict(region_id=region['id'],tag=tag.strip(),direction=data['direction'],
                    require_charge=data['require_charge'],enabled=data['enabled'],deleted=False)

    @staticmethod
    def _time_sql(key):
        # key comes only from the fixed source-code call sites below.
        return ("CASE WHEN length(CAST(summary AS BLOB))<="+str(MAX_SUMMARY_BYTES)+
                " THEN CASE WHEN json_valid(summary) AND json_type(summary,'$."+key+
                "') IN ('integer','real') THEN json_extract(summary,'$."+key+"') END END")

    def _timeline(self, db, vehicle, targets, now):
        if db is None or not targets: return []
        start, end = self._time_sql('start_time'), self._time_sql('end_time')
        lower = min(r.get('start_time') or r['end_time'] for r in targets)
        upper = max(r['end_time'] for r in targets)
        visible = visible_clause(db)
        prior = db.execute('SELECT '+end+' FROM monitor_events WHERE vehicle=? AND kind=\'trip_end\' AND '+visible+
                           ' AND '+end+'<=? ORDER BY '+end+' DESC,id DESC LIMIT 1',(vehicle,lower)).fetchone()
        following = db.execute('SELECT '+start+' FROM monitor_events WHERE vehicle=? AND kind=\'trip_end\' AND '+visible+
                               ' AND '+start+'>=? ORDER BY '+start+' ASC,id ASC LIMIT 1',(vehicle,upper)).fetchone()
        lower = prior[0] if prior else lower
        upper = min(now,following[0]) if following else now
        if upper<lower: return []
        result=[]
        cursor=db.execute('SELECT id,kind,summary FROM monitor_events WHERE vehicle=? '
                          "AND kind IN ('trip_end','charge_end') AND "+visible+
                          ' AND '+end+'>=? AND ('+start+'<=? OR '+start+' IS NULL) '
                          'ORDER BY '+end+',id LIMIT ?', (vehicle,lower,upper,MAX_CONTEXT+1))
        for identity,kind,encoded in cursor:
            check_cancelled()
            if len(result)>=MAX_CONTEXT: raise ValueError('关联停车段记录过多，请缩小范围。')
            try: row=project(identity,kind,json.loads(encoded))
            except (ValueError,TypeError,RecursionError): row=None
            if row and row['end_time']<=now:result.append(row)
        return result

    def _endpoints(self, db, vehicle, targets, saved, corrections):
        regions=[r for r in saved['records'] if not r['deleted']]
        if db is None:return {},regions
        has_points=db.execute("SELECT 1 FROM sqlite_master WHERE name='observations'").fetchone()
        samples=[]
        if has_points:
            from .parking_origin import parking_origin
            from .parking_destination import parking_destination
            for r in targets:
                start,end=r.get('start_time'),r['end_time']
                ordered=start is not None and end>start
                first=endpoint(db,vehicle,start,min(start+180000,end),True) if ordered else None
                last=endpoint(db,vehicle,max(start if ordered else 0,end-180000),end,False) if start is None or ordered else None
                evidence={}
                for side,value,infer in (('start',first,parking_origin),('end',last,parking_destination)):
                    if value is None and (side=='end' or ordered):
                        estimate=infer(db,vehicle,r)
                        if estimate:
                            value=estimate['sample_time'],estimate['point'];evidence[side]={k:v for k,v in estimate.items() if k!='point'}
                    if side=='start':first=value
                    else:last=value
                if first and last and first[0]==last[0]:first=last=None
                for side,value in (('start',first),('end',last)):
                    if value:samples.append(dict(event_id=r['id'],side=side,time=value[0],point=value[1],evidence=evidence.get(side,dict(source='trusted_endpoint'))))
        clustered=cluster_endpoints(samples,regions)
        index=RegionIndex(regions);found={}
        for sample in samples:
            centre=clustered['point_centres'].get((sample['event_id'],sample['side']),sample['point'])
            region=index.pick(centre)
            found[(sample['event_id'],sample['side'])]=dict(region_id=region['id'] if region else None,
                source=sample['evidence'].get('source','trusted_endpoint'),sample_time=sample['time'])
        # Explicit owner-scoped endpoint assignment is label evidence, never fabricated GPS.
        for record in corrections['records']:
            if record['deleted']:continue
            body=record['body'];key=(body.get('record_id'),body.get('side'))
            if body.get('action')=='reject':found.pop(key,None)
            elif body.get('action')=='assign' and any(r['id']==body.get('target_key') for r in regions):
                found[key]=dict(region_id=body['target_key'],source='user_confirmation',sample_time=None)
        return found,regions

    @staticmethod
    def _evaluate(event,rule,points,timeline,regions,now):
        evidence=dict(region_id=rule['region_id'],tag=rule['tag'],direction=rule['direction'],
                      partial=event.get('partial',True),charge_ids=[],sides=[],parking_intervals=[])
        if event['end_time']>now:return dict(result='pending',reason='future_event',evidence=evidence)
        if not rule['enabled'] or rule.get('deleted'):return dict(result='outside',reason='rule_paused',evidence=evidence)
        if not any(r['id']==rule['region_id'] for r in regions):return dict(result='pending',reason='place_missing',evidence=evidence)
        allowed=['end'] if rule['direction']=='arrive' else ['start'] if rule['direction']=='depart' else ['start','end']
        matches=[side for side in allowed if points.get((event['id'],side),{}).get('region_id')==rule['region_id']]
        evidence['sides']=[dict(side=side,**points[(event['id'],side)]) for side in matches]
        if not matches:return dict(result='outside' if any((event['id'],side) in points for side in allowed) else 'pending',reason='place_unmatched',evidence=evidence)
        if not rule['require_charge']:return dict(result='matched',reason='place_and_direction',evidence=evidence)
        trips=[r for r in timeline if r['kind']=='trip_end' and r['id']!=event['id']]
        charges=[r for r in timeline if r['kind']=='charge_end']
        for side in matches:
            if side=='end':
                lower=event['end_time'];next_start=min((r['start_time'] for r in trips if r.get('start_time') is not None and r['start_time']>=lower),default=None)
                upper=next_start if next_start is not None else now
            else:
                upper=event.get('start_time')
                if upper is None:continue
                lower=max((r['end_time'] for r in trips if r['end_time']<=upper),default=None)
                if lower is None:continue
                next_start=upper
            evidence['parking_intervals'].append(dict(side=side,start_time=lower,end_time=next_start))
            for charge in charges:
                first,last=charge.get('start_time'),charge['end_time']
                if first is None or not lower<=first<last<=upper:continue
                # Any intervening movement, including a fragment, breaks the stop.
                if any((r.get('start_time') is None and lower<r['end_time']<=last) or
                       (r.get('start_time') is not None and r['start_time']<last and r['end_time']>lower)
                       for r in trips):continue
                evidence['charge_ids'].append(charge['id'])
        evidence['charge_ids']=sorted(set(evidence['charge_ids']))
        return dict(result='matched' if evidence['charge_ids'] else 'pending',
                    reason='same_parking_charge' if evidence['charge_ids'] else 'charging_evidence_missing',evidence=evidence)

    def _decisions(self,db,owner,vehicle,event_ids):
        if not self._exists(db):return {},{}
        found,excluded={},{}
        identities=sorted(set(event_ids))
        for offset in range(0,len(identities),400):
            chunk=identities[offset:offset+400];where=' AND event_id IN ('+','.join('?' for _ in chunk)+')'
            for r,e,v,body in db.execute('SELECT rule_id,event_id,version,body FROM place_tag_decisions WHERE owner=? AND vehicle=?'+where,(owner,vehicle,*chunk)):
                found[(r,e)]=dict(version=v,**json.loads(body))
                if len(found)>MAX_PAIRS:raise ValueError('规则匹配记录过多，请缩小范围。')
            for r,e,value in db.execute('SELECT rule_id,event_id,excluded FROM place_tag_exclusions WHERE owner=? AND vehicle=?'+where,(owner,vehicle,*chunk)):
                excluded[(r,e)]=bool(value)
                if len(excluded)>MAX_PAIRS:raise ValueError('规则排除记录过多，请缩小范围。')
        return found,excluded

    def _build(self,db,track_db,owner,vehicle,targets,versions,rule=None,history=False,now=None):
        if len(targets)>MAX_TARGETS:raise ValueError('本月行程超过 1000 条，请缩小历史匹配范围。')
        canonical=[]
        if track_db is not None:
            for offset in range(0,len(targets),400):
                identities=[r['id'] for r in targets[offset:offset+400]]
                rows=track_db.execute('SELECT id,kind,summary FROM monitor_events WHERE vehicle=? AND kind=\'trip_end\' AND '+visible_clause(track_db)+' AND id IN ('+','.join('?' for _ in identities)+') ORDER BY id',(vehicle,*identities))
                for identity,kind,encoded in rows:
                    try:row=project(identity,kind,json.loads(encoded))
                    except (ValueError,TypeError,RecursionError):row=None
                    if row:canonical.append(row)
        targets=sorted(canonical,key=lambda r:(r['end_time'],r['id']))
        saved,corrections,annotations=self._personal(db,owner,vehicle)
        points,regions=self._endpoints(track_db,vehicle,targets,saved,corrections)
        now=int(time.time()*1000) if now is None else now;timeline=self._timeline(track_db,vehicle,targets,now)
        existing,exclusions=self._decisions(db,owner,vehicle,[r['id'] for r in targets])
        by_rule={};by_version={r['version']:r for r in versions}
        for version in versions:by_rule.setdefault(version['id'],[]).append(version)
        ids=sorted(by_rule);candidates=[]
        if len(targets)*(1 if rule else len(ids))>MAX_PAIRS:raise ValueError('规则匹配过多，请缩小范围。')
        effective_times={key:[r['effective_at'] for r in rows] for key,rows in by_rule.items()}
        for event in targets:
            for rule_id in ([rule['id']] if rule else ids):
                old=existing.get((rule_id,event['id']))
                if rule:selected=rule
                elif old:selected=by_version.get(old['version'])
                else:
                    position=bisect_left(effective_times[rule_id],event['end_time'])-1
                    selected=by_rule[rule_id][position] if position>=0 else None
                if not selected:continue
                evaluated=self._evaluate(event,selected,points,timeline,regions,now)
                excluded=exclusions.get((rule_id,event['id']),False)
                before=bool(old and old['result']=='matched' and not excluded)
                after=evaluated['result']=='matched' and not excluded
                change='excluded' if excluded else 'add' if after and not before else 'remove' if before and not after else 'update' if after and old.get('tag')!=selected['tag'] else 'unchanged'
                if not rule and old is None and evaluated['result']=='outside':continue
                if len(candidates)>=MAX_PAIRS:raise ValueError('规则匹配过多，请缩小范围。')
                candidates.append(dict(event_id=event['id'],rule_id=rule_id,version=selected['version'],tag=selected['tag'],
                                       start_time=event.get('start_time'),end_time=event['end_time'],excluded=excluded,change=change,**evaluated))
        token=digest(dict(owner=owner,vehicle=vehicle,rule=rule,history=history,versions=versions,targets=targets,
                          timeline=timeline,points=sorted((list(k),v) for k,v in points.items()),saved=saved,
                          corrections=corrections,annotations=annotations,existing=sorted((list(k),v) for k,v in existing.items()),
                          exclusions=sorted((list(k),v) for k,v in exclusions.items()),candidates=candidates))
        counts={k:sum(r['change']==k for r in candidates) for k in ('add','remove','update','unchanged','excluded')}
        counts['pending']=sum(r['result']=='pending' and not r['excluded'] for r in candidates)
        return dict(token=token,counts=counts,rows=candidates)

    @staticmethod
    def _write(db,owner,vehicle,rows):
        changed=False
        for row in rows:
            body={k:row[k] for k in ('tag','result','reason','evidence')};encoded=json.dumps(body,sort_keys=True,separators=(',',':'))
            old=db.execute('SELECT version,body FROM place_tag_decisions WHERE owner=? AND vehicle=? AND rule_id=? AND event_id=?',
                           (owner,vehicle,row['rule_id'],row['event_id'])).fetchone()
            if old==(row['version'],encoded):continue
            db.execute('INSERT OR REPLACE INTO place_tag_decisions VALUES(?,?,?,?,?,?)',
                       (owner,vehicle,row['rule_id'],row['event_id'],row['version'],encoded));changed=True
        if changed:
            db.execute('INSERT INTO place_tag_decision_revisions VALUES(?,?,1) ON CONFLICT(owner,vehicle) '
                       'DO UPDATE SET revision=revision+1',(owner,vehicle))

    def _targets(self,vehicle,date):
        window=period_window('month',date)
        return [r for r in self.events.between(vehicle,window['start'],window['end'])['events'] if r['kind']=='trip_end']

    def update(self,owner,vehicle,data,guard=None):
        self.store._key(owner,vehicle,'tags')
        action=data.get('action');write=action not in ('place-rule-preview','place-rule-history-preview')
        if action not in ('place-rule-preview','place-rule-save','place-rule-history-preview','place-rule-history-apply',
                          'place-rule-pause','place-rule-resume','place-rule-delete','place-rule-exclude','place-rule-include'):
            raise ValueError('地点标注规则操作无效。')
        targets=self._targets(vehicle,data.get('date')) if action in ('place-rule-preview','place-rule-save','place-rule-history-preview','place-rule-history-apply') else []
        with self.store.connect(write=write) as db:
            if db is None:raise ValueError('请先保存地点区域。')
            with db:
                db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                versions=self._versions(db,owner,vehicle);revision=versions[-1]['version'] if versions else 0
                if type(data.get('revision')) is not int or data['revision']!=revision:raise ValueError('规则已有更新，请重新读取并预览。')
                latest={r['id']:r for r in versions};old=latest.get(data.get('id'))
                if data.get('id') and (old is None or old.get('deleted') and action not in ('place-rule-exclude','place-rule-include')):raise ValueError('规则不存在或不属于当前车辆。')
                if action in ('place-rule-preview','place-rule-save'):
                    saved,_,_=self._personal(db,owner,vehicle);body=self._draft(data,saved)
                    if not old and len([r for r in latest.values() if not r.get('deleted')])>=100:raise ValueError('每辆车最多 100 条地点标注规则。')
                    # Deterministic draft ID makes preview/save tokens comparable without writing a draft.
                    identity=old['id'] if old else 'place_rule_'+digest([owner,vehicle,revision,body])[:32]
                    rule=dict(id=identity,version=revision+1,effective_at=0,**body)
                elif old is None:raise ValueError('请选择已保存的规则。')
                else:rule=old
                if action in ('place-rule-preview','place-rule-save','place-rule-history-preview','place-rule-history-apply'):
                    with self.events.connect() as track_db:
                        if track_db is not None:track_db.execute('BEGIN')
                        preview=self._build(db,track_db,owner,vehicle,targets,versions,rule=rule,history=action.startswith('place-rule-history-'))
                    if action.endswith('preview'):
                        if guard:guard()
                        return dict(preview,revision=revision,rule=rule,applied=False)
                    if data.get('preview_token' if action=='place-rule-save' else 'token')!=preview['token']:
                        raise ValueError('行程、地点、充电或标注已变化，请重新预览。')
                    self._schema(db)
                    if action=='place-rule-history-apply':
                        self._write(db,owner,vehicle,preview['rows'])
                        if guard:guard()
                        return dict(preview,revision=revision,applied=True)
                elif action in ('place-rule-exclude','place-rule-include'):
                    event=self.events.get(vehicle,data.get('event_id'))
                    if event['kind']!='trip_end':raise ValueError('请选择当前车辆已结束行程。')
                    existing,_=self._decisions(db,owner,vehicle,[event['id']])
                    if (old['id'],event['id']) not in existing:raise ValueError('这趟行程没有该规则的匹配记录。')
                    self._schema(db);db.execute('INSERT OR REPLACE INTO place_tag_exclusions VALUES(?,?,?,?,?)',
                        (owner,vehicle,old['id'],event['id'],int(action=='place-rule-exclude')))
                    db.execute('INSERT INTO place_tag_decision_revisions VALUES(?,?,1) ON CONFLICT(owner,vehicle) DO UPDATE SET revision=revision+1',(owner,vehicle))
                    if guard:guard()
                    return dict(revision=revision)
                else:
                    body={k:old[k] for k in ('region_id','tag','direction','require_charge','enabled','deleted')}
                    body.update(enabled=action=='place-rule-resume',deleted=action=='place-rule-delete')
                    rule=dict(old,version=revision+1,**body);self._schema(db)
                if revision>=MAX_VERSIONS:raise ValueError('规则版本已达上限，请先整理规则历史。')
                effective=max(int(time.time()*1000),versions[-1]['effective_at']+1 if versions else 0)
                body={k:rule[k] for k in ('region_id','tag','direction','require_charge','enabled','deleted')}
                db.execute('INSERT INTO place_tag_rule_versions VALUES(?,?,?,?,?,?)',
                           (owner,vehicle,revision+1,rule['id'],effective,json.dumps(body,separators=(',',':'))))
                if guard:guard()
                return dict(revision=revision+1,rule=dict(rule,effective_at=effective))

    def decisions(self,owner,vehicle,targets,guard=None,now=None):
        if not targets:return {}
        with self.store.connect() as db:
            versions=self._versions(db,owner,vehicle)
            if not versions:return {}
            db.execute('BEGIN')
            with self.events.connect() as track_db:
                if track_db is not None:track_db.execute('BEGIN')
                result=self._build(db,track_db,owner,vehicle,targets,versions,now=now)
            existing,exclusions=self._decisions(db,owner,vehicle,[r['id'] for r in targets])
        with self.store.connect(write=True) as db,db:
            db.execute('BEGIN IMMEDIATE')
            # A concurrent rule edit, historical application or exclusion wins.
            if self._versions(db,owner,vehicle)!=versions or self._decisions(db,owner,vehicle,[r['id'] for r in targets])!=(existing,exclusions):
                current,excluded=self._decisions(db,owner,vehicle,[r['id'] for r in targets]);found={}
                for (rule_id,event_id),row in current.items():
                    found.setdefault(event_id,[]).append(dict(row,rule_id=rule_id,event_id=event_id,excluded=excluded.get((rule_id,event_id),False),source='place_rule'))
                if guard:guard()
                return found
            self._write(db,owner,vehicle,result['rows'])
            if guard:guard()
        found={}
        for row in result['rows']:
            found.setdefault(row['event_id'],[]).append(dict(row,source='place_rule'))
        return found

    def collect(self,owner,vehicle,now,guard=None):
        if not self.rules(owner,vehicle)['revision']:return
        # Include long-pending stops as well as new trips: late charge data must retry.
        with self.store.connect() as db:
            cursor=self.pending_cursor.get((owner,vehicle),'')
            query=('SELECT DISTINCT event_id FROM place_tag_decisions '
                   "WHERE owner=? AND vehicle=? AND json_extract(body,'$.result')='pending' "
                   'AND event_id>? ORDER BY event_id LIMIT 100')
            pending=[r[0] for r in db.execute(query,(owner,vehicle,cursor))]
            if not pending and cursor:pending=[r[0] for r in db.execute(query,(owner,vehicle,''))]
            self.pending_cursor[(owner,vehicle)]=pending[-1] if pending else ''
        with self.events.connect() as db:
            if db is None:return
            end=self._time_sql('end_time')
            rows=db.execute('SELECT id,kind,summary FROM monitor_events WHERE vehicle=? AND kind=\'trip_end\' AND '+visible_clause(db)+
                            ' AND '+end+'>=? AND '+end+'<=? ORDER BY '+end+' DESC,id DESC LIMIT 100',(vehicle,now-48*3600000,now)).fetchall()
            targets=[]
            for identity,kind,encoded in rows:
                try:r=project(identity,kind,json.loads(encoded))
                except (ValueError,TypeError,RecursionError):r=None
                if r:targets.append(r)
        known={r['id'] for r in targets}
        for identity in pending:
            if identity in known:continue
            try:r=self.events.get(vehicle,identity)
            except ValueError:continue
            if r['end_time']<=now:targets.append(r)
        # Separate old retries from recent trips so a late record cannot expand a query across years.
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        months={}
        for row in targets:
            key=datetime.fromtimestamp(row['end_time']/1000,timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m')
            months.setdefault(key,[]).append(row)
        for batch in months.values():self.decisions(owner,vehicle,batch,guard=guard,now=now)
