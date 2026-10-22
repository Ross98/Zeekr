# -*- coding: utf-8 -*-
"""Independent macOS resource observer. No vehicle queries, killing or deletion."""
import argparse
import ctypes
import json
import math
import os
import plistlib
import pwd
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .delivery_state import DeliveryBusy, delivery_lock
from .notifications import BarkSender, DeliveryError
from .storage import DEFAULT_PATH, load, save
from .resource_conditions import observations, advance, active_conditions, signature, overall

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
    current={pid:dict(rows[pid], is_root=pid in roots) for pid in group}
    valid=bool(previous) and 0<elapsed<=3*INTERVAL
    complete=valid and {pid for pid in current if current[pid]['is_root']}=={pid for pid in (previous or {}) if previous[pid].get('is_root')}
    for pid,row in current.items():
        old=(previous or {}).get(pid)
        if old is None:
            if row['age']>elapsed+3:complete=False
        elif abs(row['age']-old['age']-elapsed)>3 or row['cpu']<old['cpu']:
            complete=False
    if any(pid in rows for pid in set(previous or {})-group):complete=False
    # ps -S includes reaped children in their parent. Compare aggregate counters,
    # not per-PID deltas, to avoid counting an exited child twice.
    increment=sum(row['cpu'] for row in current.values())-sum(row['cpu'] for row in (previous or {}).values())
    cpu=increment/elapsed*100 if complete and increment>=0 else None
    complete=complete and increment>=0
    return dict(app_rss_bytes=sum(row['rss'] for row in current.values()),process_count=len(current),
                app_cpu_percent=cpu,app_cpu_complete=complete),current


def native(command):
    return subprocess.check_output(command,text=True,stderr=subprocess.DEVNULL,
                                   timeout=5,env=dict(os.environ,LC_ALL='C'))


def host_cpu_ticks():
    # HOST_CPU_LOAD_INFO: user, system, idle, nice cumulative uint32 ticks.
    lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib')
    lib.mach_host_self.restype=ctypes.c_uint
    lib.host_statistics.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint)]
    lib.host_statistics.restype=ctypes.c_int
    lib.mach_port_deallocate.argtypes=[ctypes.c_uint,ctypes.c_uint]
    ticks=(ctypes.c_uint*4)();count=ctypes.c_uint(4);host=lib.mach_host_self()
    try:
        if lib.host_statistics(host,3,ticks,ctypes.byref(count))!=0 or count.value!=4:raise OSError('Host CPU unavailable')
        return tuple(ticks)
    finally:
        task=ctypes.c_uint.in_dll(lib,'mach_task_self_').value
        lib.mach_port_deallocate(task,host)


def host_cpu_delta(before,after):
    increments=[(new-old) % 2**32 for old,new in zip(before,after)]
    if len(increments)!=4 or not sum(increments):raise ValueError('Invalid CPU window')
    return (sum(increments)-increments[2])/sum(increments)*100


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def probe_origin(origin):
    # No credentials, redirects, vehicle queries, proxy shortcuts or TLS bypass.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    for suffix,expected in (('/',200),('/api/state',401)):
        try:
            with opener.open(origin+suffix,timeout=2) as response:status=response.status
        except urllib.error.HTTPError as error:
            status=error.code;error.close()
        except (OSError,ValueError):return False
        if status!=expected:return False
    return True


def configured_origin():
    home=Path(pwd.getpwuid(os.getuid()).pw_dir)
    with (home/'Library/LaunchAgents/local.zeekr.web.plist').open('rb') as stream:
        origin=plistlib.load(stream)['EnvironmentVariables']['ZEEKR_PUBLIC_ORIGIN']
    parsed=urlsplit(origin)
    if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):raise ValueError('Invalid HTTPS origin')
    return origin


def observer_enabled(root):
    try:
        home=Path(pwd.getpwuid(os.getuid()).pw_dir)
        with (home/'Library/LaunchAgents/local.zeekr.resources.plist').open('rb') as stream:
            config=plistlib.load(stream)
        expected=Path(config['EnvironmentVariables']['HOME'])/'Library/Application Support/ZeekrControl'
        return Path(root).resolve()==expected.resolve()
    except (OSError,ValueError,KeyError,TypeError):return False


def observer_sample(root,now):
    try:
        state=ResourceHealth(root).cached();checked=state.get('checked_at')
        fresh=type(checked) in (int,float) and 0<=now-checked<=3*INTERVAL
    except (OSError,ValueError,TypeError):fresh=False
    return dict(observer_health=fresh)


class NativeSampler:
    def __init__(self, run=native, host_reader=host_cpu_ticks, probe=probe_origin, origin_reader=configured_origin):
        self.run=run;self.previous=None;self.checked=None
        self.host_reader=host_reader;self.host_previous=None;self.host_checked=None
        self.probe=probe;self.origin_reader=origin_reader

    def measure(self):
        sample=dict(collector_pid=os.getpid(),host_cpu_percent=None,memory_pressure=None,app_cpu_percent=None,
                    app_cpu_complete=False,app_rss_bytes=None,process_count=None,
                    missing_services=[],sample_errors=[])
        try:
            ticks=self.host_reader();now=time.monotonic()
            elapsed=now-self.host_checked if self.host_checked is not None else 0
            if self.host_previous is not None and 0<elapsed<=3*INTERVAL:
                sample['host_cpu_percent']=host_cpu_delta(self.host_previous,ticks)
                sample['host_cpu_window_seconds']=elapsed
            self.host_previous=ticks;self.host_checked=now
        except (ValueError,OSError,subprocess.SubprocessError):
            self.host_previous=None;self.host_checked=None;sample['sample_errors'].append('host_cpu')
        try:
            sample['logical_cpus']=os.cpu_count()
            sample['physical_memory_bytes']=int(self.run(['/usr/sbin/sysctl','-n','hw.memsize']).strip())
        except (ValueError,OSError,subprocess.SubprocessError):pass
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
            rows=parse_processes(self.run(['/bin/ps','-S','-axo','uid=,pid=,ppid=,rss=,time=,etime=']))
            if any(pid not in rows or rows[pid]['uid']!=os.getuid() for pid in roots):raise ValueError()
            now=time.monotonic();elapsed=now-self.checked if self.checked is not None else 0
            metrics,self.previous=process_sample(rows,roots,self.previous,elapsed)
            sample.update(metrics);self.checked=now
        except (ValueError,OSError,subprocess.SubprocessError):
            self.previous=None;self.checked=None;sample['sample_errors'].append('processes')
        sample['endpoints']={'local':self.probe('http://127.0.0.1:18765')}
        try:sample['endpoints']['https']=self.probe(self.origin_reader())
        except (OSError,ValueError,KeyError,TypeError):sample['endpoints']['https']=False
        return sample


def classify(sample, previous='healthy'):
    records = observations(sample)
    levels = [item['observed'] for item in records.values()]
    for level in ('critical', 'warning', 'unknown', 'warming_up'):
        if level in levels:
            return level, [item['reason'] for item in records.values() if item['observed'] == level]
    return 'healthy', []


class ResourceHealth:
    def __init__(self, root, sender=None, filename='resource-health.json'):
        self.root=Path(root);self.path=self.root/filename;self.sender=sender

    def cached(self):
        encoded=load(self.path).get('state')
        return json.loads(encoded) if encoded else {}

    def save(self,state):
        save(self.path,{'state':json.dumps(state,ensure_ascii=False,allow_nan=False)})

    def migrate(self, state):
        if 'conditions' in state:return
        records={}
        old=state.get('level', 'healthy')
        reasons=state.get('reasons', [])
        # Preserve a legacy incident and its delivery outcome across deployment;
        # old aggregate streaks cannot be attributed and are intentionally reset.
        mapping={'主机 CPU 持续高占用':'host_cpu', 'Zeekr 进程树 CPU 持续超预算':'app_cpu',
                 'Zeekr 进程树内存持续超预算':'app_rss', '系统内存压力严重':'memory_pressure',
                 '系统内存压力升高':'memory_pressure'}
        for reason in reasons:
            key=mapping.get(reason)
            if key and old in ('warning', 'critical'):
                category='budget' if key.startswith('app_') else 'system'
                level='warning' if category=='budget' else old
                records[key]=dict(level=level,reason=reason,category=category)
            elif reason=='Zeekr 服务任务不可用':
                for label in state.get('sample', {}).get('missing_services', []):
                    records['service:'+label]=dict(level='critical',reason=label+' 服务任务不可用',category='availability')
        if old=='unknown':
            for key,item in observations(state.get('sample', {})).items():
                if item['category']=='monitoring' and item['observed']=='unknown':
                    records[key]=dict(item,level='unknown')
        state['conditions']=records
        state['incident']=signature(records)

    def message(self,state):
        sample=state['sample'];active=active_conditions(state['conditions'])
        supported={k:v for k,v in active.items() if v.get('observed')==v['level']}
        categories={item['category'] for item in supported.values()}
        if not active:title='✅ Zeekr 已确认异常恢复'
        elif 'availability' in categories:title='⚠️ Zeekr 服务可用性异常'
        elif 'system' in categories:title='⚠️ Zeekr 系统资源压力'
        elif 'monitoring' in categories:title='⚠️ Zeekr 资源监测失效'
        else:title='⚠️ Zeekr 进程预算提醒'
        body=[item['reason'] for item in supported.values()]
        if state.get('recovered_conditions'):
            body.append('已恢复：'+'；'.join(state['recovered_conditions']))
            if active:title+='（部分异常恢复）'
        if len(supported)!=len(active):body.append('另有此前异常尚未证实恢复；当前读数不支持重新断言其仍在超限。')
        for key,label,scale,unit in [('host_cpu_percent','主机 CPU',1,'%'),
                                    ('app_cpu_percent','Zeekr CPU（100%=一核）',1,'%'),
                                    ('app_rss_bytes','Zeekr 进程树 RSS',MIB,' MiB')]:
            if 'observer_health' in sample:break
            value=sample.get(key)
            body.append(label+'：'+('暂不可用' if value is None else '%.1f%s'%(value/scale,unit)))
        if 'observer_health' not in sample:
            labels={'normal':'正常','warning':'升高','critical':'严重'}
            body.append('系统内存压力：'+labels.get(sample.get('memory_pressure'),'暂不可用'))
            if sample.get('host_cpu_window_seconds') is not None:
                body.append('主机 CPU 为最近 %.0f 秒平均值。'%sample['host_cpu_window_seconds'])
            if sample.get('logical_cpus') and sample.get('app_cpu_percent') is not None:
                body.append('主机 %d 个逻辑核；进程 CPU 占全机约 %.1f%%。'%(sample['logical_cpus'],sample['app_cpu_percent']/sample['logical_cpus']))
            body.append('RSS 含共享页重复统计，超预算不等于系统内存不足；预算不是系统硬限制。')
        body.append('各原因分别连续巡检确认；未自动停止服务或清理数据。')
        return title,'\n'.join(body)

    def tick(self,sample,now=None,can_send=None):
        now=time.time() if now is None else now
        state=self.cached();last=state.get('checked_at')
        if last is not None and 0<=now-last<INTERVAL:
            pid=sample.get('collector_pid')
            if pid is not None and pid != state.get('monitor_pid'):
                state['monitor_pid']=pid
                if state.get('notification_state')=='sending':state['notification_state']='uncertain'
                self.save(state)
            return state
        if state.get('notification_state')=='sending':state['notification_state']='uncertain'
        self.migrate(state)
        prior=state['incident'];records=state['conditions']
        old_active={key:dict(value) for key,value in active_conditions(records).items()}
        consecutive=last is not None and 0<now-last<=INTERVAL*1.5
        current=observations(sample,records)
        advance(records,current,consecutive,CONFIRMATIONS)
        incident=signature(records);active=active_conditions(records)
        state.update(sample=sample,checked_at=now,monitor_pid=sample.get('collector_pid'),
                     level=overall(records),incident=incident,
                     reasons=[item['reason'] for item in active.values()])
        observed,_=classify(sample)
        state.update(observed_level=observed,streak=max((item['streak'] for item in records.values() if 'streak' in item), default=0))
        supported={key:item for key,item in active.items() if item.get('observed')==item['level']}
        if incident!=prior:
            state.update(notification_state='pending',retry_at=now,
                         recovered_conditions=[value['reason'] for key,value in old_active.items() if key not in active])
        elif incident and supported and all(item.get('streak',0)>=CONFIRMATIONS for item in supported.values()):
            if state.get('notification_state')=='sent' and now-state.get('attempt_at',now)>=REMINDER:
                state.update(notification_state='pending',retry_at=now)
        due=state.get('notification_state') in ('pending','failed') and now>=state.get('retry_at',0)
        # Do not resend an obsolete cause while its recovery is being confirmed.
        # A newly confirmed sensor failure may report inability to verify the old
        # incident, rather than repeat a stale pressure assertion.
        if not due or active and not supported or self.sender is None or can_send is not None and not can_send():
            self.save(state);return state
        state.update(notification_state='sending',attempt_at=now)
        self.save(state)
        if can_send is not None and not can_send():
            state['notification_state']='pending';self.save(state);return state
        try:
            self.sender(*self.message(state));state['notification_state']='sent'
            state.pop('recovered_conditions',None)
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
                started=time.monotonic();sample_time=time.time()
                # Anchor confirmation spacing to iteration start. Probe duration
                # jitter must not turn a 60-second cadence into skipped samples.
                try:monitor.tick(sampler.measure(),now=sample_time,can_send=lambda:not stop.is_set())
                except Exception:print('资源巡检状态无法保存；请检查磁盘与权限。',flush=True)
                stop.wait(max(0,INTERVAL-(time.monotonic()-started)))
    except DeliveryBusy:return


if __name__=='__main__':main()
