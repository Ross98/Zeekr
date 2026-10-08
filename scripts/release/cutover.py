import fcntl,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
base=Path('/opt/zeekr-control')
with (base/'.deploy.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    record=json.loads((base/'.release-ready.json').read_text());candidate=Path(record['candidate']);previous=Path(record['previous'])
    baseline=json.loads((base/'.release-baseline.json').read_text());changes=json.loads((base/'.release-changes.json').read_text())
    assert (base/'current').is_symlink() and (base/'current').resolve()==previous,'Active release changed'
    for name,value in baseline['manifest'].items():assert hashlib.sha256((previous/name).read_bytes()).hexdigest()==value,'Baseline drift'
    import importlib.util
    spec=importlib.util.spec_from_file_location('release_workflow',base/'.release-workflow.py');workflow=importlib.util.module_from_spec(spec);spec.loader.exec_module(workflow)
    reports_installed=Path('/etc/systemd/system/zeekr-reports.service').is_file()
    stop_services=['zeekr-control','zeekr-monitor']+(['zeekr-reports'] if reports_installed else [])
    assert set(workflow.inputs(candidate)+list(changes)+['release-manifest.json'])==set(record['candidate_hashes']), 'Candidate input set changed'
    for name,value in record['candidate_hashes'].items():assert hashlib.sha256((candidate/name).read_bytes()).hexdigest()==value,'Candidate drift'
    size=int(subprocess.check_output(['du','-sb','/var/lib/zeekr-control'],text=True).split()[0])
    assert shutil.disk_usage(base).free>size+256*1024*1024,'Insufficient backup space'
    backup=Path(record['backup']);assert not backup.exists(),'Backup already exists'
    try:
     subprocess.run(['systemctl','stop',*stop_services],check=True)
     backup.mkdir()
     subprocess.run(['cp','-a','/var/lib/zeekr-control/.',str(backup)],check=True)
     for path in Path('/var/lib/zeekr-control').rglob('*'):
      copied=backup/path.relative_to('/var/lib/zeekr-control')
      if path.is_file() and not path.is_symlink():
       assert hashlib.sha256(path.read_bytes()).digest()==hashlib.sha256(copied.read_bytes()).digest(),'Backup mismatch'
       src=path.stat();dst=copied.stat();assert (src.st_uid,src.st_gid,src.st_mode & 0o777)==(dst.st_uid,dst.st_gid,dst.st_mode & 0o777),'Backup metadata mismatch'
      elif path.is_dir() and not path.is_symlink():
       src=path.stat();os.chown(copied,src.st_uid,src.st_gid)
     src=Path('/var/lib/zeekr-control').stat();os.chown(backup,src.st_uid,src.st_gid)
     print('STOPPED_STATE_BACKUP_VERIFIED',flush=True)
     temp=base/'.current-release';assert not temp.exists() and not temp.is_symlink()
     temp.symlink_to(candidate);os.replace(temp,base/'current')
     services=workflow.runtime_services(candidate,reports_installed)
     subprocess.run(['systemctl','start',*services],check=True)
     for service in [*services,'nginx']:
      subprocess.run(['systemctl','is-active','--quiet',service],check=True)
     for service in services:
      for attempt in range(100):
       pid=subprocess.check_output(['systemctl','show',service,'-p','MainPID','--value'],text=True).strip()
       if pid!='0' and Path('/proc/'+pid+'/cwd').resolve()==candidate:break
       time.sleep(.2)
      else:raise AssertionError(service+' process has wrong release')
     print('CUTOVER_SUCCESS',str(candidate),flush=True)
    except BaseException:
     subprocess.run(['systemctl','stop',*stop_services],check=True)
     if (Path(str(candidate))/'zeekr_control/delivery_state.py').is_file():
      subprocess.run(['sudo','-u','zeekr-control','env','HOME=/var/lib/zeekr-control','PYTHONDONTWRITEBYTECODE=1','/usr/bin/python3','-c',"import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from zeekr_control.delivery_state import normalize_preparation_for_rollback; print('DELIVERY_ROLLBACK_NORMALIZED',normalize_preparation_for_rollback(Path('/var/lib/zeekr-control/Library/Application Support/ZeekrControl')))",str(candidate)],check=True)
     temp=base/'.current-release-rollback'
     if temp.exists() or temp.is_symlink():temp.unlink()
     temp.symlink_to(previous);os.replace(temp,base/'current')
     subprocess.run(['systemctl','start',*workflow.runtime_services(previous,reports_installed)])
     print('ROLLBACK_APPLIED',flush=True)
     raise
