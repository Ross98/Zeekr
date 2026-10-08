"""Authenticated, read-only notification projection. Never returns message payloads."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

from .archive_reader import _private
from .periodic_report import report_id
from .periodic_schedule import next_times
from .storage import load
from .errors import ApiError

STATES={'pending','preparing','ready','sending','sent','failed','uncertain','skipped','cancelled','local'}
ACTIVE={'pending','preparing','ready','sending'}


@contextmanager
def readonly(path):
    if not path.exists():
        yield None;return
    _private(path.parent,directory=True);_private(path)
    db=sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True,timeout=2)
    db.row_factory=sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON');yield db
    finally:db.close()


def columns(db,table):
    return {row[1] for row in db.execute('PRAGMA table_info('+table+')')} if db else set()


def number(value):
    return value if type(value) in (int,float) and 0<=value<10**15 else None


def part(state,attempts=0,next_at=None,sent_at=None,error=None,preparations=0):
    if state is None:return None
    state='uncertain' if state=='unknown' else 'pending' if state=='retry' else state
    state=state if isinstance(state,str) and state in STATES else 'uncertain'
    code=('result_unknown' if state=='uncertain' else
          'preparation_failed' if state=='failed' and any(x in str(error) for x in ('prepar','准备','生成')) else
          'send_failed' if state=='failed' else None)
    return dict(state=state,error_code=code,attempts=number(attempts) or 0,
                prepare_attempts=number(preparations) or 0,next_attempt_at=number(next_at),last_sent_at=number(sent_at))


def service(root,name,now):
    try:data=load(root/name)
    except Exception:data={}
    try:stamp=int(data.get('heartbeat',data.get('last_tick','0')))
    except (ValueError,TypeError):stamp=0
    status=data.get('status','not_started')
    allowed={'fresh','unchanged','running','ready','paused','cooldown','retrying','blocked','degraded','error','stopped','not_started'}
    status=status if status in allowed else 'degraded'
    allowance=90000
    if name=='monitor-health.json':
        try:allowance=max(180000,int(data.get('next_check',0))-stamp+60000)
        except (ValueError,TypeError):pass
    online=status not in ('stopped','not_started') and stamp>0 and 0<=now-stamp<=allowance
    return dict(status=status,online=online,last_heartbeat_at=stamp or None,
                error_code='service_unavailable' if status in ('blocked','degraded','error') else None)


def read_health(root,*,owner=None,vehicle=None,context=None,now_ms=None):
    root=Path(root);now=int(time.time()*1000) if now_ms is None else now_ms
    result=dict(schema_version=1,context=context,as_of=now,
        services={key:service(root,path,now) for key,path in
            [('collector','monitor-health.json'),('delivery','delivery-health.json'),('reports','periodic-reports-health.json')]},
        summary=dict(failed_events=0,uncertain_events=0,pending_events=0,oldest_pending_at=None,last_sent_at=None),
        events=[],periodic_reports=[],system_alerts={})
    try:settings=load(root/'periodic-reports-settings.json')
    except Exception:settings={}
    enabled=settings.get('enabled')=='1'
    result['services']['reports'].update(enabled=enabled,next_due=next_times(now) if enabled else None)
    if not enabled:result['services']['reports']['status']='disabled'
    def count(event):
        parts=[p for p in event['parts'].values() if p]
        states={p['state'] for p in parts};summary=result['summary']
        if 'failed' in states:summary['failed_events']+=1
        elif 'uncertain' in states:summary['uncertain_events']+=1
        if states & ACTIVE:
            summary['pending_events']+=1
            created=number(event.get('created_at'))
            if created is not None:summary['oldest_pending_at']=min(summary['oldest_pending_at'] or created,created)
        sent=[p['last_sent_at'] for p in parts if p['last_sent_at'] is not None]
        if sent:summary['last_sent_at']=max(summary['last_sent_at'] or 0,*sent)
    def unavailable(source):
        result.setdefault('unavailable_sources',[]).append(source)
    if vehicle:
        try:
            with readonly(root/'tracks.sqlite3') as db:
                cols=columns(db,'monitor_events')
                if cols:
                    alerts=columns(db,'monitor_event_alerts');media=columns(db,'monitor_event_media')
                    a=('a.delivery AS bark,a.attempts AS bark_attempts,a.next_attempt AS bark_next,a.sent_at AS bark_sent,a.error AS bark_error' if alerts else 'NULL AS bark,0 AS bark_attempts,NULL AS bark_next,NULL AS bark_sent,NULL AS bark_error')
                    m=('m.delivery AS image,m.attempts AS image_attempts,m.next_attempt AS image_next,m.sent_at AS image_sent,m.error AS image_error' if media else 'NULL AS image,0 AS image_attempts,NULL AS image_next,NULL AS image_sent,NULL AS image_error')
                    prep='m.prepare_attempts AS image_preparations' if 'prepare_attempts' in media else '0 AS image_preparations'
                    joins=(' LEFT JOIN monitor_event_alerts a ON a.event_id=e.id' if alerts else '')+(' LEFT JOIN monitor_event_media m ON m.event_id=e.id' if media else '')
                    query='SELECT e.id,e.kind,e.created,e.delivery,e.attempts,e.next_attempt,e.sent_at,e.error,'+a+','+m+','+prep+' FROM monitor_events e'+joins+' WHERE e.vehicle=? ORDER BY e.created DESC,e.rowid DESC'
                    for r in db.execute(query,(vehicle,)):
                        kind=r['kind'] if r['kind'] in ('trip_start','trip_end','charge_start','charge_end') else 'vehicle_event'
                        event=dict(id=r['id'],kind=kind,created_at=number(r['created']),parts={
                            'bark':part(r['bark'],r['bark_attempts'],r['bark_next'],r['bark_sent'],r['bark_error']),
                            'text':None if kind=='trip_start' or kind=='charge_start' and r['bark'] is not None else part(r['delivery'],r['attempts'],r['next_attempt'],r['sent_at'],r['error']),
                            'image':part(r['image'],r['image_attempts'],r['image_next'],r['image_sent'],r['image_error'],r['image_preparations'])})
                        count(event)
                        if len(result['events'])<30:result['events'].append(event)
        except (OSError,ValueError,sqlite3.Error):unavailable('vehicle')
    if owner and vehicle:
        try:
            with readonly(root/'periodic-reports.sqlite3') as db:
                cols=columns(db,'reports')
                if cols:
                    # Legacy identities are verified against the requested account;
                    # a read never adopts or changes an unscoped record.
                    metadata=columns(db,'report_delivery_metadata')
                    scope=' WHERE (m.owner_key=? AND m.vehicle_key=?) OR m.owner_key IS NULL' if metadata else ''
                    projection='r.*,m.owner_key,m.vehicle_key,m.created_at,m.updated_at,m.text_sent_at,m.image_sent_at,m.text_error,m.image_error,m.image_prepare_attempts' if metadata else 'r.*'
                    join=' LEFT JOIN report_delivery_metadata m USING(id)' if metadata else ''
                    rows=db.execute('SELECT '+projection+' FROM reports r'+join+scope+' ORDER BY r.rowid DESC',(owner,vehicle) if scope else ())
                    for raw in rows:
                        r=dict(raw)
                        try:
                            payload=json.loads(r['payload']);period=payload['period'];start=payload['start_date'];end=payload['end_date']
                            if period not in ('day','week','month') or r['id']!=report_id(owner,vehicle,period,start,end):continue
                        except (ValueError,TypeError,KeyError):continue
                        event=dict(id=r['id'],period=period,start_date=start,end_date=end,
                            created_at=number(r.get('created_at') or payload.get('generated_at')),parts={
                            'text':part(r['text'],r['text_attempts'],r['next_at'],r.get('text_sent_at'),r.get('text_error')),
                            'image':part(r['image'],r['image_attempts'],r['next_at'],r.get('image_sent_at'),r.get('image_error'),r.get('image_prepare_attempts',0))})
                        count(event)
                        if len(result['periodic_reports'])<30:result['periodic_reports'].append(event)
        except (OSError,ValueError,sqlite3.Error):unavailable('reports')
        try:
            with readonly(root/'personal.sqlite3') as db:
                if columns(db,'rule_history'):
                    for r in db.execute('SELECT id,kind,created,delivery,error FROM rule_history WHERE owner=? AND vehicle=? ORDER BY created DESC',(owner,vehicle)):
                        event=dict(id=r['id'],kind='custom_reminder',created_at=number(r['created']),parts={'text':part(r['delivery'],error=r['error']),'bark':None,'image':None})
                        count(event)
                        if len(result['events'])<60:result['events'].append(event)
                if columns(db,'tyre_outbox'):
                    for r in db.execute('SELECT id,created,bark,wecom,attempts_bark,attempts_wecom,next_bark,next_wecom FROM tyre_outbox WHERE owner=? AND vehicle=? ORDER BY created DESC',(owner,vehicle)):
                        event=dict(id=r['id'],kind='tyre_alert',created_at=number(r['created']),parts={'image':None,
                            'bark':part(r['bark'],r['attempts_bark'],r['next_bark']),'text':part(r['wecom'],r['attempts_wecom'],r['next_wecom'])})
                        count(event)
                        if len(result['events'])<60:result['events'].append(event)
        except (OSError,ValueError,sqlite3.Error):unavailable('personal')
    try:
        state=json.loads(load(root/'storage-health.json').get('state','{}'))
        result['system_alerts']['storage']={'parts':{
            'text':part(state.get('notification_state')),'bark':part(state.get('alert_notification_state'))},
            'last_attempt_at':number(state.get('attempt_at',0)*1000)}
    except (OSError,ValueError,TypeError,ApiError):unavailable('storage')
    try:
        with readonly(root/'system-notifications.sqlite3') as db:
            if columns(db,'auth_outbox'):
                row=db.execute('SELECT state,created,sent_at,error FROM auth_outbox ORDER BY generation DESC LIMIT 1').fetchone()
                if row:result['system_alerts']['auth']={'parts':{'bark':part(row['state'],sent_at=row['sent_at'],error=row['error'])},'last_attempt_at':number(row['created'])}
    except (OSError,ValueError,sqlite3.Error):unavailable('auth')
    for alert in result['system_alerts'].values():
        count(dict(parts=alert['parts'],created_at=alert.get('last_attempt_at')))
    result['events'].sort(key=lambda event:event['created_at'] or 0,reverse=True)
    result['events']=result['events'][:30]
    result['summary']['complete']=not result.get('unavailable_sources')
    return result
