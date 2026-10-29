"""Explicit, backed-up one-day P-gear resegmentation. Never sends notifications."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time

from .archive_reader import ArchiveReader, _private
from .delivery_state import delivery_lock
from .monitor import Monitor
from .personal_store import account_scope
from .snapshots import session_scope
from .storage import load
from .tracks import day_bounds
from .trip_visibility import cancel_event_delivery, has_sending_delivery
from .usage_events import project

POLICY='p-gear-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM monitor_events WHERE kind='trip_end' ORDER BY id")]


def earlier_digest(db, lower):
    old=[r for r in rows(db) if json.loads(r['summary']).get('end_time',lower)<lower]
    evidence=[]
    for row in old:
        parts={}
        for table in ('monitor_event_alerts','monitor_event_media','report_metric_index'):
            parts[table]=[dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE event_id=?',(row['id'],))]
        evidence.append([row,parts])
    return digest(evidence)


def build_plan(database, vehicle, date, replayed, *, context=None):
    lower,upper=day_bounds(date)
    with closing(sqlite3.connect(Path(database).absolute().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        changes=[]
        for original in rows(db):
            if original['vehicle']!=vehicle:continue
            body=json.loads(original['summary'])
            start,end=body.get('start_time'),body.get('end_time')
            if end is None or not lower<=end<upper or body.get('segmentation_policy')==POLICY:continue
            if body.get('manual_completion'):continue
            if start is None or start<lower:raise ValueError('跨日期行程不能自动重分段。')
            parts=[]
            for r in replayed:
                b=json.loads(r['summary'])
                if r['vehicle']==vehicle and start<=b['start_time'] and b['end_time']<=end:
                    parts.append(dict(r))
            parts.sort(key=lambda r:json.loads(r['summary'])['start_time'])
            # A replay extending across the original boundary is never silently ignored.
            for r in replayed:
                b=json.loads(r['summary'])
                if r['vehicle']==vehicle and b['start_time']<end and b['end_time']>start and r not in parts:
                    raise ValueError('回放越过原行程边界。')
            if len(parts)<2:continue
            bodies=[json.loads(r['summary']) for r in parts]
            if (parts[0]['id']!=original['id'] or bodies[0]['start_time']!=start or bodies[-1]['end_time']!=end
                    or any(a['end_time']>b['start_time'] for a,b in zip(bodies,bodies[1:]))):
                raise ValueError('重分段边界与原行程不一致。')
            for field in ('distance_km','soc_delta'):
                if body.get(field) is None or any(b.get(field) is None for b in bodies) or abs(sum(b[field] for b in bodies)-body[field])>.000001:
                    raise ValueError('重分段里程或电量不守恒。')
            for part,b in zip(parts,bodies):
                if b.get('segmentation_policy')!=POLICY or project(part['id'],'trip_end',b) is None:
                    raise ValueError('回放摘要缺少新规则证据。')
            changes.append(dict(original=original,parts=parts))
        plan=dict(version=1,policy=POLICY,date=date,vehicle=vehicle,lower=lower,upper=upper,
                  earlier_digest=earlier_digest(db,lower),changes=changes)
        if context is not None:plan['context']=context
        plan['id']=digest(plan)
        return plan


def _exists(db, table, schema='main'):
    return bool(db.execute('SELECT 1 FROM '+schema+'.sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone())


def _backup(path, destination):
    with closing(sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('修复备份校验失败。')
    destination.chmod(0o600)


def apply_plan(root, plan, backup):
    root,backup=Path(root),Path(backup)
    _private(root,directory=True);_private(root/'tracks.sqlite3')
    unsigned={k:v for k,v in plan.items() if k!='id'}
    if plan.get('id')!=digest(unsigned) or plan.get('policy')!=POLICY or day_bounds(plan['date'])!=(plan['lower'],plan['upper']):
        raise ValueError('修复清单校验失败。')
    if not plan['changes']:return False
    def guard():
        if 'context' in plan:
            session=load(root/'session.json')
            if (plan['context']!=dict(owner=account_scope(session),session=session_scope(session))
                    or load(root/'monitor-binding.json').get('vehicle_key')!=plan['vehicle']):
                raise ValueError('账号、会话或车辆绑定已变化。')
    with delivery_lock(root/'notifications.lock'), closing(sqlite3.connect(root/'tracks.sqlite3',timeout=10)) as db:
        guard()
        db.row_factory=sqlite3.Row
        if _exists(db,'trip_split_repairs') and db.execute('SELECT 1 FROM trip_split_repairs WHERE id=?',(plan['id'],)).fetchone():return False
        personal=root/'personal.sqlite3'
        if personal.exists():
            _private(personal)
            db.execute('ATTACH DATABASE ? AS personal',(str(personal),))
            if db.execute('PRAGMA personal.journal_mode').fetchone()[0]!='delete':
                raise ValueError('个人库不支持本次跨库原子修复。')
        if db.execute('PRAGMA main.journal_mode').fetchone()[0]!='delete':
            raise ValueError('行程库不支持本次跨库原子修复。')
        db.execute('BEGIN IMMEDIATE')
        try:
            if earlier_digest(db,plan['lower'])!=plan['earlier_digest']:raise ValueError('之前的历史已变化，停止修复。')
            state=db.execute('SELECT payload FROM monitor_state WHERE vehicle=?',(plan['vehicle'],)).fetchone()
            active=json.loads(state[0]).get('trip') if state else None
            for change in plan['changes']:
                old=change['original'];identity=old['id'];body=json.loads(old['summary'])
                current=db.execute('SELECT * FROM monitor_events WHERE id=?',(identity,)).fetchone()
                if current is None or dict(current)!=old or has_sending_delivery(db,identity):raise ValueError('原行程或发送状态已变化，停止修复。')
                if active and active['start']['time']<body['end_time']:raise ValueError('进行中行程与修复范围相交。')
                if not plan['lower']<=body['start_time']<body['end_time']<plan['upper']:raise ValueError('修复越过授权日期。')
                for part in change['parts'][1:]:
                    if db.execute('SELECT 1 FROM monitor_events WHERE id=?',(part['id'],)).fetchone():raise ValueError('拆分目标已存在。')
                if personal.exists() and _exists(db,'records','personal'):
                    if db.execute('SELECT 1 FROM personal.records WHERE vehicle=? AND deleted=0 AND body LIKE ?',
                                  (plan['vehicle'],'%'+identity+'%')).fetchone():raise ValueError('行程有人工标注，不能自动改挂。')
                if personal.exists():
                    for table in ('commute_decisions','place_tag_exclusions'):
                        if _exists(db,table,'personal') and db.execute('SELECT 1 FROM personal.'+table+' WHERE vehicle=? AND event_id=? AND excluded=1',(plan['vehicle'],identity)).fetchone():
                            raise ValueError('行程有人工排除决定，停止自动修复。')
            # Revalidate the untrusted plan's boundaries/totals from the locked source.
            checked=build_plan(root/'tracks.sqlite3',plan['vehicle'],plan['date'],
                               [p for c in plan['changes'] for p in c['parts']],context=plan.get('context'))
            if checked!=plan:raise ValueError('修复清单与当前记录不匹配。')
            backup.mkdir(parents=True,mode=0o700,exist_ok=False)
            _backup(root/'tracks.sqlite3',backup/'tracks.before.sqlite3')
            if personal.exists():_backup(personal,backup/'personal.before.sqlite3')
            (backup/'plan.json').write_text(json.dumps(plan,ensure_ascii=False));(backup/'plan.json').chmod(0o600)
            db.execute('CREATE TABLE IF NOT EXISTS trip_split_repairs(id TEXT PRIMARY KEY,vehicle TEXT,date TEXT,body TEXT,created INTEGER)')
            for change in plan['changes']:
                old=change['original'];identity=old['id']
                for index,part in enumerate(change['parts']):
                    b=json.loads(part['summary'])
                    b['historical_resegmentation']=dict(policy=POLICY,source_event_id=identity,date=plan['date'],no_notification=True)
                    encoded=json.dumps(b,ensure_ascii=False)
                    if index==0:
                        # Retain the original notification message/status/attempts as historical evidence.
                        db.execute('UPDATE monitor_events SET summary=? WHERE id=?',(encoded,identity))
                        cancel_event_delivery(db,plan['vehicle'],identity,'历史重分段，不补发通知')
                    else:
                        db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created,delivery,error) VALUES(?,?,?,?,?,?,'local',?)",
                            (part['id'],plan['vehicle'],'trip_end',encoded,part['message'],part['created'],'历史重分段，不补发通知'))
                    report=b.get('report_v2',{});metrics={k:v for k,v in report.get('metrics',{}).items() if type(v) in (int,float)}
                    db.execute('INSERT OR REPLACE INTO report_metric_index VALUES(?,?,?,?,?,?,?)',
                        (part['id'],plan['vehicle'],'trip_end',int(b['end_time']),report.get('decoder_version',''),int(bool(b.get('partial'))),json.dumps(metrics)))
                if personal.exists():
                    for table in ('commute_decisions','commute_evidence','place_tag_decisions'):
                        if _exists(db,table,'personal'):
                            db.execute('DELETE FROM personal.'+table+' WHERE vehicle=? AND event_id=?',(plan['vehicle'],identity))
            db.execute('CREATE TABLE IF NOT EXISTS trip_record_revisions(vehicle TEXT PRIMARY KEY,revision INTEGER NOT NULL)')
            db.execute('INSERT INTO trip_record_revisions VALUES(?,1) ON CONFLICT(vehicle) DO UPDATE SET revision=revision+1',(plan['vehicle'],))
            db.execute('INSERT INTO trip_split_repairs VALUES(?,?,?,?,?)',(plan['id'],plan['vehicle'],plan['date'],json.dumps(plan,ensure_ascii=False),int(time.time()*1000)))
            if earlier_digest(db,plan['lower'])!=plan['earlier_digest']:raise ValueError('修复触及之前历史，已取消。')
            guard()
            db.commit()
            return True
        except BaseException:
            db.rollback();raise


def prepare(root, date):
    root=Path(root);session=load(root/'session.json');vehicle=load(root/'monitor-binding.json')['vehicle_key']
    lower,upper=day_bounds(date)
    with tempfile.TemporaryDirectory(prefix='zeekr-trip-split-') as folder:
        replay=Monitor(Path(folder)/'tracks.sqlite3')
        # Seed only earlier ended reports for historical comparison; no outbox replay.
        with closing(sqlite3.connect((root/'tracks.sqlite3').absolute().as_uri()+'?mode=ro',uri=True)) as source:
            source.row_factory=sqlite3.Row
            existing=rows(source)
            current=[r for r in existing if r['vehicle']==vehicle and lower<=json.loads(r['summary']).get('end_time',0)<upper]
            profiles=[json.loads(r['summary']).get('report_v2',{}).get('profile_snapshot',{}) for r in current]
            if not profiles:raise ValueError('日期内没有可回放的行程。')
            profile=profiles[0]
            if any(p!=profile for p in profiles):raise ValueError('日期内车型配置变化，不能自动回放。')
            with replay.tracks.connect() as db:
                for row in existing:
                    if json.loads(row['summary']).get('end_time',upper)<lower:
                        keys=list(row);db.execute('INSERT INTO monitor_events('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',list(row.values()))
                for row in source.execute('SELECT * FROM report_metric_index WHERE end_time<?',(lower,)):
                    db.execute('INSERT INTO report_metric_index VALUES(?,?,?,?,?,?,?)',tuple(row))
        for record,raw in ArchiveReader(root/'snapshot-archive').iter_records(session_scope(session),vehicle,lower,upper,limit=None):
            replay.observe(vehicle,raw,record['observed_at'],profile=profile,
                           battery_capacity_kwh=profile.get('battery_capacity_kwh'))
        with replay.tracks.connect() as db:
            db.row_factory=sqlite3.Row
            replayed=[dict(r) for r in db.execute("SELECT * FROM monitor_events WHERE kind='trip_end' AND vehicle=?",(vehicle,))
                      if json.loads(r['summary'])['end_time']>=lower]
        return build_plan(root/'tracks.sqlite3',vehicle,date,replayed,
                          context=dict(owner=account_scope(session),session=session_scope(session)))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('plan','apply'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--date');parser.add_argument('--backup',type=Path);args=parser.parse_args()
    if args.action=='plan':
        plan=prepare(args.root,args.date);args.plan.write_text(json.dumps(plan,ensure_ascii=False));args.plan.chmod(0o600)
        print(json.dumps(dict(changes=len(plan['changes']),segments=sum(len(c['parts']) for c in plan['changes']),date=plan['date'])))
    else:
        if args.backup is None:parser.error('--backup is required for apply')
        plan=json.loads(args.plan.read_text())
        if not plan.get('context'):raise ValueError('修复清单缺少账号与会话绑定。')
        if load(args.root/'monitor-binding.json').get('vehicle_key')!=plan['vehicle']:raise ValueError('当前车辆绑定已变化。')
        print(json.dumps(dict(applied=apply_plan(args.root,plan,args.backup))))


if __name__=='__main__':main()
