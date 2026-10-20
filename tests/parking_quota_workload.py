"""Z15 offline worker. Only synthetic paths; imports the pinned candidate."""
import argparse
import gc
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark_archive_capacity import raw
from zeekr_control.archive_reader import ArchiveReader
from zeekr_control.snapshot_archive import SnapshotArchive, BEIJING
from zeekr_control.parking_analytics import ParkingAnalytics
from zeekr_control.analysis_jobs import AnalysisJobs
from zeekr_control.tracks import day_bounds
import zeekr_control.parking_analytics as analytics
from zeekr_control.analysis_work import SampleStore
from zeekr_control.usage_events import UsageEvents

DAY = 86400000
GAP_START = day_bounds('2026-08-16')[0]+12*3600000
GAP_END = GAP_START+3600000


def label(stamp):
    return datetime.fromtimestamp(stamp/1000, BEIJING).strftime('%Y-%m-%d')


def save(path, value):
    temporary=path.with_suffix('.writing')
    temporary.write_text(json.dumps(value,ensure_ascii=False));temporary.replace(path)


def matrix_plans():
    plans = []
    for period in ('day', 'month'):
        lower = day_bounds('2026-08-16' if period=='day' else '2026-08-01')[0]
        upper = day_bounds('2026-08-17' if period=='day' else '2026-09-01')[0]
        for history in ('short', 'long'):
            first = day_bounds('2026-08-01' if history=='short' else '2026-07-01')[0]
            last = first+(31 if history=='short' else 90)*DAY
            for boundary in ('complete', 'missing_before', 'missing_after', 'none'):
                plans.append(dict(case='-'.join((period,history,boundary)),range=period,history=history,
                    boundary=boundary,query_lower=lower,query_upper=upper,
                    history_lower=first,history_upper=last,cadence_ms=10000))
    return plans


def seed_archive(root, plan):
    root = Path(root);root.mkdir(parents=True,exist_ok=True);root.chmod(0o700)
    writer = SnapshotArchive(root/'archive')
    current = db = None
    payloads, reads = [], []
    def flush():
        if reads:
            db.executemany('INSERT OR IGNORE INTO payloads VALUES (?,?,?,?)',payloads)
            db.executemany('INSERT INTO reads(scope_key,vehicle_key,state_time,fetched_at,observed_at,source,digest) VALUES (?,?,?,?,?,?,?)',reads)
            db.commit();payloads.clear();reads.clear()
    try:
        for observed in range(plan['history_lower'],plan['history_upper'],plan['cadence_ms']):
            stamp=GAP_START-plan['cadence_ms'] if GAP_START<=observed<GAP_END else observed
            body=raw(stamp)
            encoded=json.dumps(body,separators=(',',':')).encode()
            month=datetime.fromtimestamp(observed/1000,BEIJING).strftime('%Y/%m')
            if month!=current:
                if db is not None:flush();db.close()
                writer.append('synthetic','car',encoded.decode(),stamp,observed,observed,'monitor')
                db=sqlite3.connect(root/'archive'/(month+'.sqlite3'));current=month
                continue
            digest=hashlib.sha256(encoded).hexdigest()
            payloads.append((digest,'gzip-json-v1',len(encoded),gzip.compress(encoded,compresslevel=1,mtime=0)))
            reads.append(('synthetic','car',stamp,observed,observed,'monitor',digest))
            if len(reads)==512:flush()
        if db is not None:flush()
    finally:
        if db is not None:db.close()
    return (plan['history_upper']-plan['history_lower'])//plan['cadence_ms']


def seed_events(root, plan):
    folder=Path(root)/'events';folder.mkdir(exist_ok=True,mode=0o700)
    path=folder/(plan['case']+'.sqlite3')
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE monitor_events (id TEXT,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
        def save(identity,kind,start,end):
            summary=dict(start_time=start,end_time=end,duration_seconds=(end-start)/1000,
                         start_soc=70,end_soc=70,soc_delta=0,partial=False)
            db.execute('INSERT INTO monitor_events VALUES (?,?,?,?,?)',
                       (identity,'car',kind,json.dumps(summary),end))
        if plan['boundary'] in ('complete','missing_after'):
            save('before','trip_end',plan['query_lower']-3600000,plan['query_lower'])
        if plan['boundary'] in ('complete','missing_before'):
            save('after','trip_end',plan['query_upper'],plan['query_upper']+3600000)
        # Daily zero-SOC-gain synthetic summaries exercise historical event reads
        # and phase boundaries without introducing trips that repair missing ends.
        for index,start in enumerate(range(plan['history_lower'],plan['history_upper'],DAY)):
            charge=start+3*3600000
            if charge+60000<plan['history_upper']:save('charge'+str(index),'charge_end',charge,charge+60000)
    path.chmod(0o600)


def expected_bounds(plan):
    start=plan['query_lower'] if plan['boundary'] in ('complete','missing_after') else plan['history_lower']
    end=plan['query_upper'] if plan['boundary'] in ('complete','missing_before') else plan['history_upper']-plan['cadence_ms']
    return start,end


def check_contract(response, plan):
    assert response['calculation_version']==6
    assert len(response['events'])==1,'one uninterrupted-location parking event'
    event=response['events'][0];start,end=expected_bounds(plan)
    assert (event['start_time'],event['end_time'])==(start,end),'long event was clipped or extended'
    assert event['duration_seconds']==(end-start)/1000
    assert event['gap_count']>=1 and 'gap' in event['reasons']
    assert event['status']=='uncertain' and event['soc_drop'] is None and event['estimated_kwh'] is None
    assert event['parking_status']=='parked'
    assert event['open']==(plan['boundary'] in ('none','missing_after'))


def query_once(root, plan, *, full_payload=False, ready=None, threshold=500, progress=None):
    counters=dict(metadata_rows=0,payload_decodes=0,event_rows=0)
    phases={};intervals=[];current=['setup']
    def snapshot():
        return dict(counters=counters.copy(),phases_seconds=phases.copy(),phase=current[0],read_intervals=intervals[:])
    def publish():
        if progress:save(Path(progress),snapshot())
    rows0,payload0,records0=ArchiveReader._iter_rows,ArchiveReader._payload,ArchiveReader.iter_records
    decode0=UsageEvents._decode
    def rows(reader,*args,**kwargs):
        intervals.append([args[2],args[3]])
        for row in rows0(reader,*args,**kwargs):
            counters['metadata_rows']+=1
            if ready is not None and counters['metadata_rows']>=threshold:ready.set()
            if counters['metadata_rows']%5000==0:publish()
            yield row
    def payload(row):
        counters['payload_decodes']+=1;return payload0(row)
    def decode(*args):
        counters['event_rows']+=1;return decode0(*args)
    def records(reader,*args,**kwargs):
        if full_payload:kwargs.pop('payload_when',None)
        return records0(reader,*args,**kwargs)
    def timed(name,fn):
        def run(*args,**kwargs):
            previous=current[0];current[0]=name;publish();begin=time.monotonic()
            try:return fn(*args,**kwargs)
            finally:phases[name]=phases.get(name,0)+time.monotonic()-begin;current[0]=previous
        return run
    begin=time.monotonic()
    try:
        with patch.object(ArchiveReader,'_iter_rows',rows),patch.object(ArchiveReader,'_payload',staticmethod(payload)),patch.object(ArchiveReader,'iter_records',records),patch.object(UsageEvents,'_decode',staticmethod(decode)),patch.object(UsageEvents,'between',timed('event_history',UsageEvents.between)),patch.object(SampleStore,'__enter__',timed('projection',SampleStore.__enter__)),patch.object(analytics,'analyze_parking',timed('legacy',analytics.analyze_parking)),patch.object(analytics,'build_events',timed('events',analytics.build_events)):
            response=ParkingAnalytics(ArchiveReader(Path(root)/'archive'),Path(root)/'events'/(plan['case']+'.sqlite3')).query('synthetic','car',label(plan['query_lower']),label(plan['query_upper']-1),86)
        elapsed=time.monotonic()-begin
        check_contract(response,plan)
        digest=hashlib.sha256(json.dumps(response,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        return dict(status='ok',elapsed_seconds=elapsed,**snapshot(),response_sha256=digest,response=response)
    except Exception as error:
        error.measurement=dict(status='error',elapsed_seconds=time.monotonic()-begin,**snapshot())
        raise


def cancel_probe(root, plan, threshold=500):
    import tempfile
    scratch=Path(tempfile.gettempdir());before=set(scratch.glob('zeekr-analysis-*'))
    ready=threading.Event();finished=threading.Event();jobs=AnalysisJobs();outcome={}
    def read():
        try:
            row=query_once(root,plan,ready=ready,threshold=threshold)
            outcome['completed_before_cancel']=True
            return 200,row['response']
        finally:finished.set()
    ticket=jobs.submit('synthetic',read)
    deadline=time.monotonic()+60
    while not ready.wait(.01):
        jobs.poll(ticket,'synthetic')
        if finished.is_set() or time.monotonic()>deadline:raise AssertionError('worker did not reach cancellation checkpoint')
    begin=time.monotonic();status,body=jobs.cancel(ticket,'synthetic');ack=time.monotonic()-begin
    assert finished.wait(10),'cancelled worker did not clean up'
    acquired=0
    while acquired<2 and time.monotonic()-begin<10:
        if jobs.slots.acquire(blocking=False):acquired+=1
        else:time.sleep(.001)
    elapsed=time.monotonic()-begin
    for _ in range(acquired):jobs.slots.release()
    return dict(status='ok',cancelled=status==200 and body.get('cancelled') is True and not outcome,
                ack_seconds=ack,cleanup_seconds=elapsed,slots_released=acquired==2,
                scratch_remaining=[str(p.name) for p in set(scratch.glob('zeekr-analysis-*'))-before])


def wait(path):
    while not path.exists():time.sleep(.02)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',choices=['prepare','pair','warm','cancel','supervise'],required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--job',type=Path)
    args=parser.parse_args();os.umask(0o077)
    if args.task=='prepare':
        plans=matrix_plans()
        for history in ('short','long'):
            selected=[p for p in plans if p['history']==history];root=args.root/history
            count=seed_archive(root,selected[0])
            for plan in selected:seed_events(root,plan)
            print(json.dumps(dict(history=history,records=count)),flush=True)
        return
    job=args.job;config=json.loads((job/'job.json').read_text());plan=config['plan']
    if args.task=='supervise':
        (job/'ready').touch();wait(job/'start')
        child=subprocess.Popen([sys.executable,__file__,'--task',config['task'],'--root',str(args.root),'--job',str(job)])
        (job/'child.pid').write_text(str(child.pid))
        code=child.wait();save(job/'done.json',dict(exit_code=code))
        wait(job/'release');return
    if args.task=='cancel':
        (job/'cancel.ready').touch();wait(job/'cancel.go')
        try:row=cancel_probe(args.root,plan)
        except Exception as error:row=dict(status='error',error_type=type(error).__name__,error=str(error)[:400])
        save(job/'cancel.result.json',row);return
    cold_ok=False
    for mode in (('warm',) if args.task=='warm' else ('cold','warm')):
        (job/(mode+'.ready')).touch();wait(job/(mode+'.go'))
        try:row=query_once(args.root,plan,progress=job/'progress.json')
        except Exception as error:row=dict(getattr(error,'measurement',{}),status='error',error_type=type(error).__name__,error=str(error)[:400])
        row['cache_state']='fresh_process_targeted_fixture_eviction' if mode=='cold' else ('same_process_after_complete_query' if cold_ok else 'partial_after_failed_query')
        if mode=='cold':cold_ok=row['status']=='ok'
        save(job/(mode+'.result.json'),row)
        del row;gc.collect()


if __name__=='__main__':main()
