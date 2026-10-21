"""Independent macOS resource observer. No vehicle queries, killing or deletion."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

from .delivery_state import DeliveryBusy, delivery_lock
from .notifications import BarkSender, DeliveryError
from .storage import DEFAULT_PATH, load, save

INTERVAL = 60
CONFIRMATIONS = 3
REMINDER = 86400
SERVICE_LABELS = ('local.zeekr.web', 'local.zeekr.monitor', 'local.zeekr.reports')
MIB = 1024**2


def cpu_seconds(value):
    days, clock = value.split('-',1) if '-' in value else ('0',value)
    result=0.0
    for part in clock.split(':'):result=result*60+float(part)
    result += int(days)*86400
    if not math.isfinite(result) or result<0:raise ValueError('Invalid process clock')
    return result


def parse_processes(text):
    result={}
    for line in text.splitlines():
        fields=line.split()
        if len(fields)!=6:raise ValueError('Incomplete process inventory')
        uid,pid,parent,rss,clock,age=fields
        row=dict(uid=int(uid),parent=int(parent),rss=int(rss)*1024,cpu=cpu_seconds(clock),age=cpu_seconds(age))
        if row['rss']<0:raise ValueError('Invalid resident size')
        result[int(pid)]=row
    if not result:raise ValueError('Empty process inventory')
    return result


def process_sample(rows, roots, previous, elapsed):
    group=set(roots)&set(rows)
    while True:
        children={pid for pid,row in rows.items() if row['parent'] in group}
        if children<=group:break
        group |= children
    current={pid:rows[pid] for pid in group}
    valid=bool(previous) and 0<elapsed<=3*INTERVAL
    complete=valid and set(current)==set(previous)
    increments=[]
    for pid,row in current.items():
        old=(previous or {}).get(pid)
        if not valid or old is None or abs(row['age']-old['age']-elapsed)>3 or row['cpu']<old['cpu']:
            complete=False;continue
        increments.append(row['cpu']-old['cpu'])
    # A partial sum is a lower bound: sufficient to detect excess, never to prove recovery.
    cpu=sum(increments)/elapsed*100 if increments else None
    return dict(app_rss_bytes=sum(row['rss'] for row in current.values()),process_count=len(current),
                app_cpu_percent=cpu,app_cpu_complete=complete),current


def native(command):
    return subprocess.check_output(command,text=True,stderr=subprocess.DEVNULL,
                                   timeout=5,env=dict(os.environ,LC_ALL='C'))


class NativeSampler:
    def __init__(self, run=native):
        self.run=run;self.previous=None;self.checked=None

    def measure(self):
        sample=dict(collector_pid=os.getpid(),host_cpu_percent=None,memory_pressure=None,app_cpu_percent=None,
                    app_cpu_complete=False,app_rss_bytes=None,process_count=None,
                    missing_services=[],sample_errors=[])
        try:
            top=self.run(['/usr/bin/top','-l','2','-s','1','-n','0'])
            idle=re.findall(r'CPU usage:.*?([0-9.]+)% idle',top)
            if not idle or not 0<=float(idle[-1])<=100:raise ValueError()
            sample['host_cpu_percent']=100-float(idle[-1])
        except (ValueError,OSError,subprocess.SubprocessError):sample['sample_errors'].append('host_cpu')
        try:
            pressure=int(self.run(['/usr/sbin/sysctl','-n','kern.memorystatus_vm_pressure_level']).strip())
            # The sysctl exports dispatch flags, not XNU's internal pressure enum.
            sample['memory_pressure']={1:'normal',2:'warning',4:'critical'}[pressure]
        except (KeyError,ValueError,OSError,subprocess.SubprocessError):sample['sample_errors'].append('memory_pressure')
        roots=[]
        for label in SERVICE_LABELS:
            try:
                job=self.run(['/bin/launchctl','print','gui/'+str(os.getuid())+'/'+label])
                pid=re.search(r'^\tpid = (\d+)$',job,re.M)
                if not pid or not re.search(r'^\tstate = running$',job,re.M):raise ValueError()
                roots.append(int(pid[1]))
            except (ValueError,OSError,subprocess.SubprocessError):sample['missing_services'].append(label)
        try:
            rows=parse_processes(self.run(['/bin/ps','-axo','uid=,pid=,ppid=,rss=,time=,etime=']))
            if any(pid not in rows or rows[pid]['uid']!=os.getuid() for pid in roots):raise ValueError()
            now=time.monotonic();elapsed=now-self.checked if self.checked is not None else 0
            metrics,self.previous=process_sample(rows,roots,self.previous,elapsed)
            sample.update(metrics);self.checked=now
        except (ValueError,OSError,subprocess.SubprocessError):
            self.previous=None;self.checked=None;sample['sample_errors'].append('processes')
        return sample


def classify(sample, previous='healthy'):
    reasons=[];critical=[]
    def over(key,warning,hard,description):
        value=sample.get(key)
        if value is None:return
        # Hysteresis reduces flapping around budgets.
        if value>=hard:critical.append(description)
        elif value>=warning*(.9 if previous in ('warning','critical') else 1):reasons.append(description)
    over('host_cpu_percent',85,95,'主机 CPU 持续高占用')
    over('app_cpu_percent',100,200,'Zeekr 进程树 CPU 持续超预算')
    over('app_rss_bytes',512*MIB,1024*MIB,'Zeekr 进程树内存持续超预算')
    if sample.get('memory_pressure')=='critical':critical.append('系统内存压力严重')
    elif sample.get('memory_pressure')=='warning':reasons.append('系统内存压力升高')
    if sample.get('missing_services'):critical.append('Zeekr 服务任务不可用')
    if critical:return 'critical',critical+reasons
    if reasons:return 'warning',reasons
    if sample.get('sample_errors'):return 'unknown',['资源指标暂不可用']
    if sample.get('app_cpu_percent') is None or not sample.get('app_cpu_complete'):
        return 'warming_up',['进程采样窗口尚不完整']
    return 'healthy',[]


class ResourceHealth:
    def __init__(self,root,sender=None):
        self.root=Path(root);self.path=self.root/'resource-health.json';self.sender=sender

    def cached(self):
        encoded=load(self.path).get('state')
        return json.loads(encoded) if encoded else {}

    def save(self,state):
        save(self.path,{'state':json.dumps(state,ensure_ascii=False,allow_nan=False)})

    def message(self,state):
        level=state['level'];sample=state['sample']
        title='✅ Zeekr 资源恢复' if level=='healthy' else '⚠️ Zeekr 资源监控告警'
        body=list(state.get('reasons',[]))
        for key,label,scale,unit in [('host_cpu_percent','主机 CPU',1,'%'),
                                    ('app_cpu_percent','Zeekr CPU（100%=一核）',1,'%'),
                                    ('app_rss_bytes','Zeekr 进程树 RSS',MIB,' MiB')]:
            value=sample.get(key)
            body.append(label+'：'+('暂不可用' if value is None else '%.1f%s'%(value/scale,unit)))
        body.append('系统内存压力：'+str(sample.get('memory_pressure') or '暂不可用'))
        body.append('连续巡检确认；未自动停止服务或清理数据。')
        return title,'\n'.join(body)

    def tick(self,sample,now=None):
        now=time.time() if now is None else now
        state=self.cached();last=state.get('checked_at')
        if last is not None and 0<=now-last<INTERVAL:
            pid=sample.get('collector_pid')
            if pid is not None and pid != state.get('monitor_pid'):
                # A new task must prove it is alive immediately, without turning
                # the same sampling interval into a second sustained observation.
                state['monitor_pid']=pid
                if state.get('notification_state')=='sending':state['notification_state']='uncertain'
                self.save(state)
            return state
        if state.get('notification_state')=='sending':state['notification_state']='uncertain'
        prior=state.get('level','healthy');level,reasons=classify(sample,prior)
        consecutive=last is not None and 0<now-last<=INTERVAL*1.5
        count=state.get('streak',0)+1 if consecutive and state.get('observed_level')==level else 1
        state.update(sample=sample,checked_at=now,observed_level=level,streak=count,
                     monitor_pid=sample.get('collector_pid'))
        state.setdefault('level','healthy')
        if count>=CONFIRMATIONS and level!='warming_up' and level!=prior:
            state.update(level=level,reasons=reasons,notification_state='pending',retry_at=now)
        elif count>=CONFIRMATIONS and level==prior and level not in ('healthy','warming_up'):
            if state.get('notification_state')=='sent' and now-state.get('attempt_at',now)>=REMINDER:
                state.update(reasons=reasons,notification_state='pending',retry_at=now)
        due=state.get('notification_state') in ('pending','failed') and now>=state.get('retry_at',0)
        # Never send a now-obsolete failure while observations await recovery confirmation.
        if not due or level!=state['level'] or self.sender is None:
            self.save(state);return state
        state.update(notification_state='sending',attempt_at=now)
        self.save(state)  # Durable intent must precede network I/O.
        try:
            self.sender(*self.message(state));state['notification_state']='sent'
        except DeliveryError as error:
            state['notification_state']='uncertain' if error.ambiguous else 'failed'
            state['retry_at']=now+(3600 if error.permanent else 900)
        except Exception:state['notification_state']='uncertain'
        self.save(state);return state


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=DEFAULT_PATH.parent)
    options=parser.add_mutually_exclusive_group();options.add_argument('--inspect',action='store_true')
    options.add_argument('--sample',action='store_true',help='Read metrics only; no state write or notification')
    args=parser.parse_args(argv)
    monitor=ResourceHealth(args.root,BarkSender(args.root/'bark.json'))
    if args.inspect:
        print(json.dumps(monitor.cached(),ensure_ascii=False,indent=2));return
    if sys.platform!='darwin':raise ValueError('Native resource monitor requires macOS')
    sampler=NativeSampler()
    if args.sample:
        print(json.dumps(sampler.measure(),ensure_ascii=False,indent=2));return
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    try:
        with delivery_lock(args.root/'resource-monitor.lock'):
            while not stop.is_set():
                started=time.monotonic()
                try:monitor.tick(sampler.measure())
                except Exception:print('资源巡检状态无法保存；请检查磁盘与权限。',flush=True)
                stop.wait(max(0,INTERVAL-(time.monotonic()-started)))
    except DeliveryBusy:return


if __name__=='__main__':main()
