"""Conservative software tyre reminders, scoped to owner and vehicle."""
import hashlib
import json
import math
from .notifications import DeliveryError, bark_time
from .delivery_state import delivery_lock
from .report_telemetry import normalize

COLLECTION='tyre_notifications'
DEFAULT=dict(enabled=True,load='light')
BASES={'light':260,'full':290}

class ObservationCancelled(Exception):
    """Configuration or sampling changed while evaluating cached evidence."""


def transition(previous,pressures,stamp,now,base):
    state=json.loads(json.dumps(previous));events=[]
    last=state.get('stamp');observed=state.get('observed')
    if type(stamp) not in (int,float) or not math.isfinite(stamp) or not -30000<=now-stamp<=180000:
        for wheel in state.get('wheels',{}).values():wheel.pop('candidate',None)
        return state,events
    if last is not None and (stamp<=last or now<=observed):
        if stamp==last and pressures!=state.get('pressures'):
            for wheel in state.get('wheels',{}).values():wheel.pop('candidate',None)
            state['pressures']=pressures
        return state,events
    gap=last is not None and (stamp-last>180000 or now-observed>180000)
    state.update(stamp=stamp,observed=now,pressures=pressures)
    wheels=state.setdefault('wheels',{})
    for name in sorted(set(wheels) | set(pressures)):
        pressure=pressures.get(name)
        wheel=wheels.setdefault(name,dict(level=0));active=wheel['level']
        if gap:wheel.pop('candidate',None)
        if type(pressure) not in (int,float) or not math.isfinite(pressure) or pressure<=0:
            wheel.pop('candidate',None);continue
        target=2 if pressure<=base*.8 else 1 if pressure<=base*.9 else 0
        recovery=active>0 and pressure>=base*.95
        if not recovery and target<=active:
            wheel.pop('candidate',None);continue
        goal=0 if recovery else target
        candidate=wheel.get('candidate')
        if not candidate or candidate['goal']!=goal:
            candidate=dict(goal=goal,count=0,first=stamp,observed=now)
        candidate['count']+=1;wheel['candidate']=candidate
        confirmed=(candidate['count']>=2 if goal==2 else candidate['count']>=3 and stamp-candidate['first']>=120000 and now-candidate['observed']>=120000)
        if confirmed:
            wheel.update(level=goal);wheel.pop('candidate',None)
            events.append(dict(wheel=name,level=goal,pressure=pressure))
    return state,events


def render_payload(events,config,pressures,stamp):
    severity=max(e['level'] for e in events)
    title=('✅ 胎压恢复' if severity==0 else '⚠️ 胎压明显偏低' if severity==2 else '⚠️ 胎压偏低')
    labels={0:'恢复',1:'偏低',2:'明显偏低'}
    lines=['%s：%s kPa（%s）'%(e['wheel'],format(e['pressure'],'.1f'),labels[e['level']]) for e in events]
    baseline='%s参考：%s kPa'%('轻载' if config['load']=='light' else '满载',BASES[config['load']])
    body='\n'.join(lines+[baseline,'车辆观测：'+bark_time(stamp),'已由连续新观测确认，请核查胎压。' if severity else '以上轮位已连续确认恢复。'])
    detail='\n'.join([title,body]+['%s：%s kPa'%(name,format(value,'.1f') if type(value) in (int,float) and value>0 else '未知') for name,value in pressures.items()]+['软件参考提醒，非厂家报警标准。','车辆云端缓存观测；轮胎独立更新时间未提供。'])
    return dict(events=events,title=title,body=body,detail=detail,pressures=pressures,stamp=stamp)


class TyreNotifications:
    def __init__(self,store):self.store=store

    @staticmethod
    def _tables(db):
        db.execute('CREATE TABLE IF NOT EXISTS tyre_states(owner TEXT,vehicle TEXT,signature TEXT,payload TEXT,PRIMARY KEY(owner,vehicle))')
        db.execute('CREATE TABLE IF NOT EXISTS tyre_outbox(id TEXT PRIMARY KEY,owner TEXT,vehicle TEXT,signature TEXT,created INTEGER,payload TEXT,bark TEXT,wecom TEXT,attempts_bark INTEGER DEFAULT 0,attempts_wecom INTEGER DEFAULT 0,next_bark INTEGER DEFAULT 0,next_wecom INTEGER DEFAULT 0)')

    def config(self,owner,vehicle):
        saved=self.store.read(owner,vehicle,COLLECTION)
        record=next((r for r in saved['records'] if r['id']=='settings' and not r['deleted']),None)
        settings=record['body'] if record else dict(DEFAULT)
        return dict(settings,revision=saved['revision'])

    def signature(self,config):return hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()

    def query(self,owner,vehicle):
        config=self.config(owner,vehicle);base=BASES[config['load']]
        history=[]
        with self.store.connect() as db:
            if db and db.execute("SELECT 1 FROM sqlite_master WHERE name='tyre_outbox'").fetchone():
                history=[dict(id=r[0],created=r[1],events=json.loads(r[2])['events'],bark=r[3],wecom=r[4]) for r in db.execute('SELECT id,created,payload,bark,wecom FROM tyre_outbox WHERE owner=? AND vehicle=? ORDER BY created DESC,rowid DESC LIMIT 30',(owner,vehicle))]
        return dict(config=config,base=base,warning=base*.9,severe=base*.8,recovery=base*.95,history=history)

    def update(self,owner,vehicle,data,guard=None):
        if data.get('action')!='save' or type(data.get('enabled')) is not bool or not isinstance(data.get('load'),str) or data['load'] not in BASES:raise ValueError('胎压提醒设置无效。')
        self.store.change(owner,vehicle,COLLECTION,'save','settings',dict(enabled=data['enabled'],load=data['load']),data.get('revision'),guard=guard)
        return self.query(owner,vehicle)

    def observe(self,owner,vehicle,raw,now,bark=None,wecom=None,guard=None):
        if guard:guard()
        config=self.config(owner,vehicle);signature=self.signature(config)
        point=normalize(raw,now)
        pressures={t['position']:t['pressure']['value'] for t in point['tyres']}
        with self.store.connect(write=True) as db:
            self._tables(db)
            with db:
                row=db.execute('SELECT signature,payload FROM tyre_states WHERE owner=? AND vehicle=?',(owner,vehicle)).fetchone()
                old=json.loads(row[1]) if row and row[0]==signature else {}
                if not row or row[0]!=signature or not config['enabled']:
                    db.execute("UPDATE tyre_outbox SET bark=CASE WHEN bark='pending' THEN 'cancelled' ELSE bark END,wecom=CASE WHEN wecom='pending' THEN 'cancelled' ELSE wecom END WHERE owner=? AND vehicle=?",(owner,vehicle))
                state,events=transition(old,pressures,point['state_time'],now,BASES[config['load']]) if config['enabled'] else ({},[])
                db.execute('INSERT OR REPLACE INTO tyre_states VALUES(?,?,?,?)',(owner,vehicle,signature,json.dumps(state)))
                if events:
                    changed={event['wheel'] for event in events}
                    pending=db.execute("SELECT id,payload FROM tyre_outbox WHERE owner=? AND vehicle=? AND (bark='pending' OR wecom='pending')",(owner,vehicle)).fetchall()
                    for old_id,encoded in pending:
                        old_payload=json.loads(encoded)
                        remaining=[e for e in old_payload.get('delivery_events',old_payload['events']) if e['wheel'] not in changed]
                        if not remaining:
                            db.execute("UPDATE tyre_outbox SET bark=CASE WHEN bark='pending' THEN 'cancelled' ELSE bark END,wecom=CASE WHEN wecom='pending' THEN 'cancelled' ELSE wecom END WHERE id=?",(old_id,))
                        else:
                            replacement=render_payload(remaining,config,old_payload['pressures'],old_payload['stamp'])
                            replacement.update(events=old_payload['events'],delivery_events=remaining)
                            db.execute('UPDATE tyre_outbox SET payload=? WHERE id=?',(json.dumps(replacement),old_id))
                    payload=render_payload(events,config,pressures,point['state_time'])
                    identity=hashlib.sha256((owner+vehicle+signature+str(point['state_time'])+json.dumps(events,sort_keys=True)).encode()).hexdigest()
                    db.execute('INSERT OR IGNORE INTO tyre_outbox(id,owner,vehicle,signature,created,payload,bark,wecom) VALUES(?,?,?,?,?,?,?,?)',(identity,owner,vehicle,signature,now,json.dumps(payload),'pending','pending'))
                    db.execute("DELETE FROM tyre_outbox WHERE owner=? AND vehicle=? AND bark NOT IN ('pending','sending') AND wecom NOT IN ('pending','sending') AND rowid NOT IN (SELECT rowid FROM tyre_outbox WHERE owner=? AND vehicle=? ORDER BY created DESC,rowid DESC LIMIT 1000)",(owner,vehicle,owner,vehicle))
                if guard:guard()
                if self.signature(self.config(owner,vehicle))!=signature:
                    raise ObservationCancelled()
        if bark is not None or wecom is not None:
            self.deliver(owner,vehicle,now,bark,wecom,guard)

    def deliver(self,owner,vehicle,now,bark,wecom,guard=None):
        with delivery_lock(self.store.path.parent/'notifications.lock'):
            self._deliver(owner,vehicle,now,bark,wecom,guard)

    def _deliver(self,owner,vehicle,now,bark,wecom,guard=None):
        signature=self.signature(self.config(owner,vehicle))
        with self.store.connect(write=True) as db:
            self._tables(db)
            with db:
                for channel in ('bark','wecom'):
                    db.execute('UPDATE tyre_outbox SET '+channel+"='uncertain' WHERE owner=? AND vehicle=? AND "+channel+"='sending'",(owner,vehicle))
            rows=db.execute("SELECT id,payload FROM tyre_outbox WHERE owner=? AND vehicle=? AND signature=? AND (bark='pending' OR wecom='pending') ORDER BY created,rowid LIMIT 10",(owner,vehicle,signature)).fetchall()
        for identity,encoded in rows:
            payload=json.loads(encoded)
            for channel,sender in [('bark',bark),('wecom',wecom)]:
                if sender is None:continue
                if guard:guard()
                if self.signature(self.config(owner,vehicle))!=signature:return
                with self.store.connect(write=True) as db:
                    with db:
                        if guard:guard()
                        if self.signature(self.config(owner,vehicle))!=signature:return
                        claimed=db.execute('UPDATE tyre_outbox SET '+channel+"='sending',attempts_"+channel+'=attempts_'+channel+'+1 WHERE id=? AND '+channel+"='pending' AND next_"+channel+'<=?',(identity,now)).rowcount
                    attempts=db.execute('SELECT attempts_'+channel+' FROM tyre_outbox WHERE id=?',(identity,)).fetchone()[0]
                if not claimed:continue
                if guard:guard()
                if self.signature(self.config(owner,vehicle))!=signature:return
                status='sent'
                try:
                    if channel=='bark':sender(payload['title'],payload['body'])
                    else:sender(payload['detail'])
                except DeliveryError as error:
                    status='uncertain' if error.ambiguous else 'failed' if error.permanent or attempts>=5 else 'pending'
                except Exception:status='uncertain'
                with self.store.connect(write=True) as db:
                    with db:db.execute('UPDATE tyre_outbox SET '+channel+'=?,next_'+channel+'=? WHERE id=?',(status,now+60000*min(16,2**(attempts-1)),identity))
