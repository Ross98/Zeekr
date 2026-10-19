"""Confirmed cached-state reminders with private, durable local history/outbox."""
import hashlib
import json
import uuid

from .notifications import DeliveryError
from .delivery_state import delivery_lock
from .summary import updated_at, number, section, SIDES
from .vehicle_state import decode

MAX_AGE=180000
MAX_GAP=600000
WINDOW_MAPPING='2026-10-19-v1'  # Owner-tested endpoints; intermediate openings use the agreed range inference.
KINDS={'low_soc':'电量低于阈值','high_soc':'电量达到阈值','parked_charging':'停车充电持续中',
       'parked_windows':'停车下电后车窗未关'}


def definition(data):
    name=data.get('name','')
    if not isinstance(name,str) or not 1<=len(name.strip())<=80:
        raise ValueError('提醒名称需为 1–80 字。')
    kind=data.get('kind')
    if not isinstance(kind,str) or kind not in KINDS:raise ValueError('提醒条件无效。')
    enabled=data.get('enabled')
    recovery=data.get('recovery')
    if type(enabled) is not bool or type(recovery) is not bool:
        raise ValueError('启停及恢复提醒须为开关值。')
    threshold=data.get('threshold',25)
    if type(threshold) is not int or not 1<=threshold<=99:
        raise ValueError('电量阈值须为 1–99 的整数。')
    confirm=data.get('confirm_seconds');cooldown=data.get('cooldown_minutes')
    if type(confirm) is not int or not 60<=confirm<=86400:
        raise ValueError('连续确认须为 60–86400 秒，至少两条新观测。')
    if type(cooldown) is not int or not 1<=cooldown<=43200:
        raise ValueError('冷却时间须为 1–43200 分钟。')
    delivery=data.get('delivery')
    if delivery not in ('in_app','wecom'):raise ValueError('提醒方式无效。')
    rule=dict(name=name.strip(),kind=kind,threshold=threshold,enabled=enabled,recovery=recovery,
              confirm_seconds=confirm,cooldown_minutes=cooldown,delivery=delivery)
    if kind=='parked_windows':rule['window_mapping']=WINDOW_MAPPING
    return rule


def windows_open(raw):
    """Owner-tested endpoints and range inference; unknown windows block decisions.

    Evidence: docs/window-evidence-2026-10-19.md. Intermediate values are
    inferred, not individually tested. Position units remain unverified.
    """
    climate=section(section(raw.get('additionalVehicleStatus')).get('climateStatus'))
    states=[]
    for side in SIDES:
        position,status=number(climate.get('winPos'+side)),number(climate.get('winStatus'+side))
        if (position,status)==(0,2):states.append(False)
        elif position is not None and 0<position<=100 and status==1:states.append(True)
        else:return None
    return any(states)


def preview(rule,raw,now):
    point=decode(raw or {})
    timestamp=point['time']
    reason='unknown_time' if timestamp is None else 'future' if timestamp>now+30000 else 'stale' if now-timestamp>MAX_AGE else None
    matches=None
    if not reason:
        if rule['kind']=='parked_windows':
            if rule.get('window_mapping')!=WINDOW_MAPPING:reason='unverified'
            elif point['off'] is not True or point['speed']!=0:reason='not_parked'
            else:
                matches=windows_open(raw or {})
                if matches is None:reason='unknown_value'
        elif rule['kind'] in ('low_soc','high_soc'):
            if point['soc'] is None:reason='unknown_value'
            else:matches=point['soc']<rule['threshold'] if rule['kind']=='low_soc' else point['soc']>=rule['threshold']
        elif rule['kind']=='parked_charging':
            if point['off'] is False or point['speed'] is not None and point['speed']>0 or point['charging'] is False:
                matches=False
            elif point['off'] is True and point['speed']==0 and point['charging'] is True:
                matches=True
            else:reason='unknown_value'
        else:reason='unverified'
    return dict(matches=matches,reason=reason or ('matching' if matches else 'not_matching'),
                state_time=timestamp,observed_at=now,soc=point['soc'])


def signature(record):
    return hashlib.sha256(json.dumps([record['body'],record['updated_at']],sort_keys=True).encode()).hexdigest()


class Reminders:
    def __init__(self,store):self.store=store

    @staticmethod
    def _tables(db):
        db.execute('''CREATE TABLE IF NOT EXISTS rule_states (
            owner TEXT,vehicle TEXT,id TEXT,signature TEXT,payload TEXT NOT NULL,
            PRIMARY KEY(owner,vehicle,id))''')
        db.execute('''CREATE TABLE IF NOT EXISTS rule_history (
            id TEXT PRIMARY KEY,owner TEXT,vehicle TEXT,rule_id TEXT,signature TEXT,
            kind TEXT,name TEXT,created INTEGER,state_time INTEGER,delivery TEXT,message TEXT,error TEXT)''')
        db.execute('CREATE INDEX IF NOT EXISTS rule_history_scope ON rule_history(owner,vehicle,created DESC)')

    @staticmethod
    def _has_tables(db):
        return bool(db and db.execute("SELECT 1 FROM sqlite_master WHERE name='rule_history'").fetchone())

    def update(self,owner,vehicle,data,guard=None):
        action=data.get('action');identity=data.get('id');body=None
        if action=='save':
            body=definition(data)
            identity=identity or 'rule_'+uuid.uuid4().hex
        result=self.store.change(owner,vehicle,'rules',action,identity,body,data.get('revision'),guard=guard)
        return dict(id=identity,revision=result['revision'],can_undo=result['can_undo'])

    def preview(self,owner,vehicle,data,raw,now):
        return preview(definition(data),raw,now)

    def query(self,owner,vehicle):
        with self.store.connect() as db:
            if db:db.execute('BEGIN')
            result=self.store._read(db,self.store._key(owner,vehicle,'rules'))
            result['history']=[];result['states']={}
            if self._has_tables(db):
                rows=db.execute('SELECT id,rule_id,kind,name,created,state_time,delivery,error FROM rule_history '
                                'WHERE owner=? AND vehicle=? ORDER BY created DESC,rowid DESC LIMIT 100',(owner,vehicle)).fetchall()
                result['history']=[dict(zip(('id','rule_id','kind','name','created','state_time','delivery','error'),row)) for row in rows]
                records={r['id']:r for r in result['records'] if not r['deleted']}
                for identity,stamp,payload in db.execute('SELECT id,signature,payload FROM rule_states WHERE owner=? AND vehicle=?',(owner,vehicle)):
                    if identity in records and stamp==signature(records[identity]):
                        state=json.loads(payload)
                        result['states'][identity]={key:state.get(key) for key in
                            ('active','count','candidate','first_time','last_time','last_observed','last_raised','reason')}
            result['history_limit']=100
            result['capabilities']=dict.fromkeys(KINDS,True)
            return result

    def recover(self):
        with delivery_lock(self.store.path.parent/'notifications.lock'):
            self._recover()

    def _recover(self):
        # Called only by the process-lock owner at startup, never by Web reads.
        if not self.store.path.exists():return
        with self.store.connect(write=True) as db,db:
            if self._has_tables(db):
                db.execute("UPDATE rule_history SET delivery='uncertain',error='发送期间进程中断，结果未确认；不会自动重发。' WHERE delivery='sending'")

    @staticmethod
    def _event(db,owner,vehicle,record,state,kind,now,timestamp):
        rule=record['body'];stamp=signature(record)
        identity=hashlib.sha256(f'{owner}:{vehicle}:{record["id"]}:{stamp}:{kind}:{timestamp}'.encode()).hexdigest()
        message=(f'车辆自定义提醒 · {"条件恢复" if kind=="recovered" else "条件成立"}\n'
                 f'{rule["name"]}\n条件：{KINDS[rule["kind"]]}'
                 +(f' {rule["threshold"]}%' if rule['kind'] in ('low_soc','high_soc') else '')
                 +f'\n车辆观测：{updated_at(timestamp)}\n已连续确认 {rule["confirm_seconds"]} 秒；缓存可能延迟。'
                 +f'\n事件编号：{identity[:16]}')
        delivery='pending' if rule['delivery']=='wecom' and (kind!='recovered' or rule['recovery']) else 'local'
        db.execute('INSERT OR IGNORE INTO rule_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   (identity,owner,vehicle,record['id'],stamp,kind,rule['name'],now,timestamp,delivery,message,''))
        db.execute('DELETE FROM rule_history WHERE owner=? AND vehicle=? AND rowid NOT IN '
                   '(SELECT rowid FROM rule_history WHERE owner=? AND vehicle=? ORDER BY created DESC,rowid DESC LIMIT 10000)',
                   (owner,vehicle,owner,vehicle))

    def observe(self,owner,vehicle,raw,now,sender=None,guard=None):
        saved=self.store.read(owner,vehicle,'rules')
        if not saved['records']:
            with self.store.connect() as db:
                if not self._has_tables(db):return
                orphan=db.execute('SELECT 1 FROM rule_states WHERE owner=? AND vehicle=? LIMIT 1',(owner,vehicle)).fetchone()
                pending=db.execute("SELECT 1 FROM rule_history WHERE owner=? AND vehicle=? AND delivery='pending' LIMIT 1",(owner,vehicle)).fetchone()
                if not orphan and not pending:return
        digest=hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.store.connect(write=True) as db,db:
            db.execute('BEGIN IMMEDIATE');self._tables(db)
            records=self.store._read(db,self.store._key(owner,vehicle,'rules'))['records']
            # Undoing creation removes a record. Retain historical outcomes but
            # discard its runtime state and cancel anything not yet sent.
            db.execute("DELETE FROM rule_states WHERE owner=? AND vehicle=? AND id NOT IN "
                       "(SELECT id FROM records WHERE owner=? AND vehicle=? AND collection='rules' AND deleted=0)",
                       (owner,vehicle,owner,vehicle))
            db.execute("UPDATE rule_history SET delivery='cancelled',error='规则已移除，未发送。' "
                       "WHERE owner=? AND vehicle=? AND delivery='pending' AND rule_id NOT IN "
                       "(SELECT id FROM records WHERE owner=? AND vehicle=? AND collection='rules' AND deleted=0)",
                       (owner,vehicle,owner,vehicle))
            for record in records:
                if record['deleted'] or not record['body']['enabled']:continue
                rule=record['body'];stamp=signature(record)
                row=db.execute('SELECT signature,payload FROM rule_states WHERE owner=? AND vehicle=? AND id=?',
                               (owner,vehicle,record['id'])).fetchone()
                state=json.loads(row[1]) if row and row[0]==stamp else dict(active=False,last_raised=None,last_time=None,count=0,candidate=None)
                observation=preview(rule,raw,now);timestamp=observation['state_time'];matches=observation['matches']
                previous=state.get('last_time')
                reset=matches is None or timestamp is None or previous is not None and timestamp<previous
                duplicate=timestamp is not None and timestamp==previous
                if duplicate and digest!=state.get('digest'):reset=True
                if reset:
                    state.update(count=0,candidate=None,first_time=None,first_observed=None)
                elif not duplicate:
                    gap=MAX_AGE if rule['kind']=='parked_windows' else MAX_GAP
                    continuous=(previous is not None and 0<timestamp-previous<=gap
                                and 0<=now-state.get('last_observed',now)<=gap)
                    if not continuous or state.get('candidate') is not matches:
                        state.update(candidate=matches,count=1,first_time=timestamp,first_observed=now)
                    else:state['count']+=1
                    confirmed=(state['count']>=2 and timestamp-state['first_time']>=rule['confirm_seconds']*1000
                               and now-state['first_observed']>=rule['confirm_seconds']*1000)
                    if confirmed and matches and not state['active']:
                        cooled=state['last_raised'] is None or now-state['last_raised']>=rule['cooldown_minutes']*60000
                        if cooled:
                            self._event(db,owner,vehicle,record,state,'raised',now,timestamp)
                            state.update(active=True,last_raised=now)
                    elif confirmed and not matches and state['active']:
                        state['active']=False
                        self._event(db,owner,vehicle,record,state,'recovered',now,timestamp)
                if timestamp is not None and (previous is None or timestamp>=previous) and observation['reason'] not in ('future','stale'):
                    state.update(last_time=timestamp,digest=digest)
                if not duplicate or reset:state['last_observed']=now
                state['reason']=observation['reason'] if not duplicate else 'revision' if reset else 'repeat'
                db.execute('INSERT OR REPLACE INTO rule_states VALUES(?,?,?,?,?)',
                           (owner,vehicle,record['id'],stamp,json.dumps(state,allow_nan=False)))
            if guard:guard()
        if sender is not None:self.deliver(owner,vehicle,raw,now,sender,guard)

    def deliver(self,owner,vehicle,raw,now,sender,guard=None):
        with delivery_lock(self.store.path.parent/'notifications.lock'):
            self._recover()
            self._deliver(owner,vehicle,raw,now,sender,guard)

    def _deliver(self,owner,vehicle,raw,now,sender,guard=None):
        # Claim under a write transaction, send outside it; one attempt per event.
        with self.store.connect() as db:
            if not self._has_tables(db):return
            ids=[r[0] for r in db.execute("SELECT id FROM rule_history WHERE owner=? AND vehicle=? AND delivery='pending' ORDER BY created,rowid LIMIT 100",(owner,vehicle))]
        for identity in ids:
            with self.store.connect(write=True) as db,db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute("SELECT rule_id,signature,kind,created,message FROM rule_history WHERE id=? AND delivery='pending'",(identity,)).fetchone()
                if not row:continue
                saved=self.store._read(db,self.store._key(owner,vehicle,'rules'))
                record=next((r for r in saved['records'] if r['id']==row[0] and not r['deleted']),None)
                valid=record and record['body']['enabled'] and signature(record)==row[1]
                observed=preview(record['body'],raw,now) if valid else None
                age=MAX_AGE if record and record['body']['kind']=='parked_windows' else MAX_GAP
                valid=bool(valid and observed['matches'] is (row[2]=='raised') and 0<=now-row[3]<=age)
                if not valid:
                    db.execute("UPDATE rule_history SET delivery='cancelled',error='条件、规则或有效时间已变化，未发送。' WHERE id=?",(identity,))
                    continue
                if guard:guard()
                db.execute("UPDATE rule_history SET delivery='sending' WHERE id=?",(identity,))
            try:
                if guard:guard()
            except Exception:
                with self.store.connect(write=True) as db,db:
                    db.execute("UPDATE rule_history SET delivery='cancelled',error='发送前账号已变化，未发送。' WHERE id=?",(identity,))
                raise
            try:
                sender(row[4]);delivery,error='sent',''
            except DeliveryError as exc:
                delivery='uncertain' if exc.ambiguous else 'failed'
                error='发送结果未确认，不会自动重发。' if exc.ambiguous else '通知被拒绝，请检查通知配置；不会自动重发。'
            except Exception:
                delivery,error='uncertain','发送结果未确认，不会自动重发。'
            with self.store.connect(write=True) as db,db:
                db.execute('UPDATE rule_history SET delivery=?,error=? WHERE id=?',(delivery,error,identity))
