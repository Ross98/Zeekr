"""Serial Z15 Docker quota measurement; never connects to a production service."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def write(path, value):
    path=Path(path);temporary=path.with_suffix('.writing')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def cg_values(group):
    row={}
    for name in ['cpu.max','cpu.stat','memory.max','memory.high','memory.swap.max',
                 'memory.peak','memory.current','memory.events','memory.stat','pids.max']:
        try:row[name]=(group/name).read_text().strip()
        except OSError:row[name]=None
    return row


def numbers(text):
    return {k:int(v) for k,v in (line.split() for line in (text or '').splitlines())}


def watch(job_name, pid, history, modes):
    """Runs only in the Docker VM controller, never on the production host."""
    job=Path('/work/jobs')/job_name
    relative=Path('/proc/'+pid+'/cgroup').read_text().split('::')[1].strip().lstrip('/')
    group=Path('/cg')/relative
    assert 'docker' in relative,'refuse non-Docker cgroup'
    (group/'memory.high').write_text('201326592')
    initial=cg_values(group)
    assert initial['cpu.max']=='25000 100000'
    assert initial['memory.max']=='268435456' and initial['memory.high']=='201326592'
    assert initial['memory.swap.max']=='0' and initial['pids.max']=='64'
    if modes[0]=='cold':
        for path in (Path('/fixtures')/history).rglob('*.sqlite3'):
            with path.open('rb') as stream:
                os.fsync(stream.fileno());os.posix_fadvise(stream.fileno(),0,0,os.POSIX_FADV_DONTNEED)
    (job/'start').touch()
    reports={}
    for mode in modes:
        deadline=time.monotonic()+30
        while not (job/(mode+'.ready')).exists():
            if (job/'done.json').exists() or time.monotonic()>deadline:break
            time.sleep(.05)
        if not (job/(mode+'.ready')).exists():break
        reset=True;peak_stream=None
        try:
            # New kernels keep resets local to this open descriptor.
            peak_stream=(group/'memory.peak').open('r+')
            peak_stream.write('0');peak_stream.flush();peak_stream.seek(0)
        except OSError:
            reset=False
            if peak_stream:peak_stream.close();peak_stream=None
        before=cg_values(group);started=time.monotonic();(job/(mode+'.go')).touch()
        limit=60 if mode=='cancel' else 600
        sampled_peak=0;events_peak={};timed_out=False
        while not (job/(mode+'.result.json')).exists():
            current=cg_values(group)
            if current['memory.current'] is not None:sampled_peak=max(sampled_peak,int(current['memory.current']))
            for key,value in numbers(current['memory.events']).items():events_peak[key]=max(events_peak.get(key,0),value)
            if (job/'done.json').exists():break
            if time.monotonic()-started>limit:
                timed_out=True
                # Kill only the supervised child in this exact Docker cgroup.
                children=Path('/proc/'+pid+'/task/'+pid+'/children').read_text().split()
                for child in children:
                    if Path('/proc/'+child+'/cgroup').read_text().split('::')[1].strip().lstrip('/')==relative:
                        os.kill(int(child),signal.SIGKILL)
                break
            time.sleep(.1)
        after=cg_values(group)
        lifetime_peak=after['memory.peak']
        if peak_stream:
            peak_stream.seek(0);after['memory.peak']=peak_stream.read().strip();peak_stream.close()
        result_path=job/(mode+'.result.json')
        result=json.loads(result_path.read_text()) if result_path.exists() else dict(
            status='hard_timeout' if timed_out else 'worker_killed',elapsed_seconds=time.monotonic()-started)
        if (job/'progress.json').exists() and result['status']!='ok':
            result['last_progress']=json.loads((job/'progress.json').read_text())
        totals=numbers(after['memory.events']) or events_peak
        prior=numbers(before['memory.events'])
        result.update(quota=initial,resource_before=before,resource_after=after,
                      sampled_current_peak_bytes=sampled_peak,memory_peak_reset=reset,
                      memory_peak_bytes=int(after['memory.peak'] or sampled_peak),lifetime_memory_peak_bytes=int(lifetime_peak or sampled_peak),
                      memory_events={key:max(0,value-prior.get(key,0)) for key,value in totals.items()},memory_events_total=totals,
                      cpu_seconds=(numbers(after['cpu.stat']).get('usage_usec',0)-numbers(before['cpu.stat']).get('usage_usec',0))/1000000)
        reports[mode]=result
    (job/'release').touch()
    print(json.dumps(reports,ensure_ascii=False),flush=True)


def docker(*args, capture=False):
    result=subprocess.run(['docker',*map(str,args)],text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,stderr=subprocess.PIPE)
    if result.returncode:raise RuntimeError('Docker operation failed: '+result.stderr[-1000:])
    return result.stdout if capture else ''


def assess(row, plan, mode, reference):
    events=row.get('memory_events',{})
    memory=row.get('memory_peak_bytes',0)
    flags=dict(completed=row.get('status')=='ok',oom_zero=events.get('oom',-1)==0 and events.get('oom_kill',-1)==0,
               hard_limit_untouched=events.get('max',-1)==0,memory_within_soft_limit=0<memory<=192*1024*1024)
    if mode=='cancel':
        flags.update(cancelled=row.get('cancelled') is True,cleanup=row.get('cleanup_seconds',999)<=2,
                     slots_released=row.get('slots_released') is True,scratch_clean=row.get('scratch_remaining')==[])
    else:
        flags.update(within_time=row.get('elapsed_seconds',9999)<=(60 if plan['range']=='day' else 300),
                     full_response_equal=reference is not None and row.get('response_sha256')==reference,
                     valid_cache_mode=mode!='warm' or row.get('cache_state')=='same_process_after_complete_query')
    return dict(checks=flags,passed=all(flags.values()))


def main():
    if len(sys.argv)>1 and sys.argv[1]=='watch':
        watch(sys.argv[2],sys.argv[3],sys.argv[4],sys.argv[5:]);return
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['source','worker','image','audit']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--cases',nargs='*');parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    lock=Path('/tmp/zeekr-z15-matrix.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    source=Path(args.source).resolve();worker=Path(args.worker).resolve();audit=Path(args.audit).resolve()
    audit.mkdir(parents=True,exist_ok=True)
    sys.dont_write_bytecode=True
    sys.path[:0]=[str(worker.parent),str(source/'tests'),str(source)]
    from parking_quota_workload import matrix_plans
    plans=matrix_plans();selected=[p for p in plans if not args.cases or p['case'] in args.cases]
    fingerprint={str(p.relative_to(source)):digest(p) for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    harness={str(worker):digest(worker),str(Path(__file__).resolve()):digest(__file__)}
    env_path=audit/'environment.json'
    if env_path.exists():
        assert args.resume,'existing run requires --resume'
        environment=json.loads(env_path.read_text());assert environment['source_hashes']==fingerprint and environment['harness_hashes']==harness
        assert environment['image']==args.image
    else:
        suffix=str(os.getpid())
        environment=dict(source=str(source),source_hashes=fingerprint,harness_hashes=harness,image=args.image,
                         data_volume='zeekr-z15-data-'+suffix,work_volume='zeekr-z15-work-'+suffix,
                         controller='zeekr-z15-controller-'+suffix,budgets=dict(day_seconds=60,month_seconds=300,hard_stop_seconds=600,cancel_seconds=2,memory_peak_bytes=192*1024*1024))
        write(env_path,environment)
        for volume in [environment['data_volume'],environment['work_volume']]:docker('volume','create',volume)
    controller=environment['controller'];data=environment['data_volume'];work=environment['work_volume']
    source_mount=str(source)+':/source:ro';harness_mount=str(worker.parent)+':/harness:ro'
    # Only this controller has cgroup write access, inside Docker's Linux VM.
    # Analysis workers are unprivileged, read-only and have no network.
    if not docker('ps','-q','--filter','name=^/'+controller+'$',capture=True).strip():
        docker('run','-d','--rm','--name',controller,'--network','none','--privileged','--cgroupns','host','--pid','host',
               '-v','/sys/fs/cgroup:/cg:rw','-v',data+':/fixtures','-v',work+':/work','-v',harness_mount,
               args.image,'python','-c','import time;time.sleep(172800)')
    try:
        if not (audit/'prepared.json').exists():
            assert not (audit/'preparing.json').exists(),'Incomplete fixture preparation: preserve failure evidence and use a fresh audit'
            write(audit/'preparing.json',dict(started=time.time()))
            docker('exec',controller,'python','-c',"import os;os.chown('/fixtures',1000,1000);os.chmod('/fixtures',0o700);os.chown('/work',1000,1000);os.chmod('/work',0o700)")
            print('PREPARING_SYNTHETIC_FIXTURES',flush=True)
            result=docker('run','--rm','--network','none','--cpus','1','--memory','512m','--memory-swap','512m','--user','1000:1000',
                '-v',data+':/fixtures','-v',source_mount,'-v',harness_mount,'--env','PYTHONPATH=/source:/source/tests','--env','PYTHONDONTWRITEBYTECODE=1',
                args.image,'python','/harness/'+worker.name,'--task','prepare','--root','/fixtures',capture=True)
            write(audit/'prepared.json',dict(output=result));print(result,flush=True)
        def run_job(plan, repeat, task, modes, suffix=''):
            job_name=plan['case']+'-r'+str(repeat)+'-'+task+suffix
            name='zeekr-z15-'+job_name
            config=dict(plan=plan,task=task)
            setup="import pathlib,json,os;p=pathlib.Path('/work/jobs')/"+repr(job_name)+";p.mkdir(parents=True,exist_ok=True);(p/'tmp').mkdir(exist_ok=True);(p/'job.json').write_text("+repr(json.dumps(config))+");os.chown(p,1000,1000);os.chmod(p,0o700);os.chown(p/'tmp',1000,1000);os.chmod(p/'tmp',0o700);os.chown(p/'job.json',1000,1000)"
            docker('exec',controller,'python','-c',setup)
            container=docker('create','--name',name,'--network','none','--cpus','0.25','--memory','256m','--memory-swap','256m','--pids-limit','64',
                '--ulimit','fsize=536870912:536870912','--user','1000:1000','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
                '-v',data+':/fixtures:ro','--mount','type=volume,src='+work+',dst=/work,volume-subpath=jobs/'+job_name,
                '-v',source_mount,'-v',harness_mount,'--env','PYTHONPATH=/source:/source/tests','--env','PYTHONDONTWRITEBYTECODE=1','--env','TMPDIR=/work/tmp',
                args.image,'python','/harness/'+worker.name,'--task','supervise','--root','/fixtures/'+plan['history'],'--job','/work',capture=True).strip()
            try:
                docker('start',container)
                pid=docker('inspect','--format','{{.State.Pid}}',container,capture=True).strip()
                text=docker('exec',controller,'python','/harness/'+Path(__file__).name,'watch',job_name,pid,plan['history'],*modes,capture=True)
                report=json.loads(text)
                logs=subprocess.run(['docker','logs',container],text=True,capture_output=True)
                (audit/(job_name+'.stderr')).write_text(logs.stdout+logs.stderr)
                return report
            finally:docker('rm','-f',container)
        for plan in selected:
            reference=None
            for repeat in range(1,args.repeats+1):
                receipt=audit/(plan['case']+'-r'+str(repeat)+'.json')
                if receipt.exists():
                    previous=json.loads(receipt.read_text())
                    reference=reference or previous['results'].get('cold',{}).get('response_sha256')
                    continue
                result=run_job(plan,repeat,'pair',['cold','warm'])
                if 'warm' not in result:result.update(run_job(plan,repeat,'warm',['warm'],'-recovery'))
                result.update(run_job(plan,repeat,'cancel',['cancel']))
                reference=reference or result.get('cold',{}).get('response_sha256')
                for mode,row in result.items():row.update(assess(row,plan,mode,reference))
                write(receipt,dict(plan=plan,repeat=repeat,results=result))
                print(json.dumps(dict(case=plan['case'],repeat=repeat,results={mode:{k:row.get(k) for k in ['status','elapsed_seconds','memory_peak_bytes','passed','error_type','cleanup_seconds']} for mode,row in result.items()})),flush=True)
            write(audit/'progress.json',dict(last_case=plan['case'],updated_at=time.time()))
        assert fingerprint=={str(p.relative_to(source)):digest(p) for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        assert harness=={str(worker):digest(worker),str(Path(__file__).resolve()):digest(__file__)}
        write(audit/'run-complete.json',dict(cases=[p['case'] for p in selected],repeats=args.repeats,source_stable=True,harness_stable=True))
    finally:
        docker('stop',controller)


if __name__=='__main__':main()
