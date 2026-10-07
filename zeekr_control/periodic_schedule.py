"""Standalone Beijing report scheduler; no historical replay and no vehicle poll."""
import argparse
from datetime import datetime,timedelta
import json
from pathlib import Path
import re
import signal
import threading
import time

from .storage import DEFAULT_PATH,load,save
from .snapshot_archive import BEIJING
from .periodic_report import PeriodicDelivery
from .periodic_summary import PeriodicSummary,report_window
from .notifications import WeComSender

SCHEDULE = {'day':0,'week':10,'month':20}
DELIVERY_WINDOW_MS = 6*3600000


def due_jobs(now,enabled_at):
    today=datetime.fromtimestamp(now/1000,BEIJING)
    date=(today-timedelta(days=1)).strftime('%Y-%m-%d')
    jobs=[]
    for period,minute in SCHEDULE.items():
        if period=='week' and today.weekday()!=0:continue
        if period=='month' and today.day!=1:continue
        due=int(today.replace(hour=8,minute=minute,second=0,microsecond=0).timestamp()*1000)
        if enabled_at<=due<=now<due+DELIVERY_WINDOW_MS:
            window=report_window(period,date)
            jobs.append(dict(period=period,date=date,due=due,start_date=window['start_date'],end_date=window['end_date']))
    return jobs


def next_times(now):
    today=datetime.fromtimestamp(now/1000,BEIJING)
    result={}
    for offset in range(33):
        day=today+timedelta(days=offset)
        for period,minute in SCHEDULE.items():
            if period in result:continue
            if period=='week' and day.weekday()!=0:continue
            if period=='month' and day.day!=1:continue
            due=day.replace(hour=8,minute=minute,second=0,microsecond=0)
            if due.timestamp()*1000>now:result[period]=due.strftime('%Y-%m-%d %H:%M')
    return result


class ScheduledReports:
    def __init__(self,session_path=DEFAULT_PATH,*,context=None,summary=None,delivery=None,sender=None):
        self.session_path=Path(session_path);root=self.session_path.parent
        self.settings=root/'periodic-reports-settings.json'
        self.health=root/'periodic-reports-health.json'
        self.context=context or self.read_context
        if summary is None:
            from .archive_reader import ArchiveReader
            from .personal_store import PersonalStore
            summary=PeriodicSummary(root/'tracks.sqlite3',ArchiveReader(root/'snapshot-archive'),PersonalStore(root/'personal.sqlite3'))
        self.summary=summary
        self.delivery=delivery or PeriodicDelivery(root/'periodic-reports.sqlite3')
        self.sender=sender or WeComSender(root/'wecom-webhook.json')

    def read_context(self):
        from .web import App
        from .snapshots import session_scope
        from .personal_store import account_scope
        app=App(self.session_path)
        try:
            with app.lock:
                session=app._read_session();app._restore_snapshot(session)
                if not session.get('accessToken') or not app.vehicle_key:raise ValueError('报表需要已确认车辆缓存')
                return session_scope(session),account_scope(session),app.vehicle_key,(app.model or {}).get('updated_time')
        finally:app.close()

    def enable(self,now=None):
        # Validate cached binding and webhook shape, without calling cloud or sender.
        self.context()
        webhook=load(self.session_path.parent/'wecom-webhook.json').get('webhook_url','')
        if not re.fullmatch(r'https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]{16,128}',webhook):
            raise ValueError('企业微信配置无效')
        previous=load(self.settings)
        if previous.get('enabled')=='1':return
        now=int(time.time()*1000) if now is None else now
        save(self.settings,dict(enabled='1',enabled_at=str(now),theme='light'))

    def tick(self,now=None):
        now=int(time.time()*1000) if now is None else now
        settings=load(self.settings)
        if settings.get('enabled')!='1':return []
        enabled_at=int(settings['enabled_at']);theme=settings.get('theme','light')
        jobs=due_jobs(now,enabled_at)
        results=[]
        if jobs:
            scope,owner,vehicle,vehicle_time=self.context()
            for job in jobs:
                state=self.delivery.lookup(owner,vehicle,job['period'],job['start_date'],job['end_date'])
                if state:
                    if state['text'] in ('sending','unknown','failed'):continue
                    if state['text']=='sent' and state['image'] in ('sent','failed','unknown','sending'):continue
                    if state['next_at']>now:continue
                report=self.summary.query(scope,vehicle,owner,job['period'],job['date'],now=now,vehicle_time=vehicle_time)
                # Cancel if account/binding/settings changed during the readonly query.
                if self.context()[:3]!=(scope,owner,vehicle) or load(self.settings)!=settings:break
                result=self.delivery.deliver(owner,vehicle,report,self.sender,theme)
                results.append(dict(period=job['period'],**result))
        save(self.health,dict(status='ready',last_tick=str(now),timezone='Asia/Shanghai',
             **{'next_'+k:v for k,v in next_times(now).items()}))
        return results

    def run(self):
        stop=threading.Event()
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
        while not stop.is_set():
            try:self.tick()
            except Exception:
                # Fixed status only: no tokens, raw payload, routes or exception text.
                save(self.health,dict(status='error',last_tick=str(int(time.time()*1000)),error='报表任务暂不可用'))
            stop.wait(30)


def main():
    parser=argparse.ArgumentParser(description='企业微信日/周/月报，北京时间08:00/08:10/08:20。')
    parser.add_argument('--session',type=Path,default=DEFAULT_PATH)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--enable',action='store_true')
    group.add_argument('--disable',action='store_true')
    group.add_argument('--status',action='store_true')
    args=parser.parse_args();worker=ScheduledReports(args.session)
    if args.enable:
        worker.enable();print('定期报表已启用。');return
    if args.disable:
        record=load(worker.settings);record['enabled']='0';save(worker.settings,record)
        print('定期报表已停用。');return
    if args.status:
        settings=load(worker.settings)
        print(json.dumps(dict(enabled=settings.get('enabled')=='1',timezone='Asia/Shanghai',
                             next=next_times(int(time.time()*1000)),health=load(worker.health)),ensure_ascii=False));return
    worker.run()


if __name__=='__main__':main()
