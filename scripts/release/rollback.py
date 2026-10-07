import fcntl,json,os,subprocess
from pathlib import Path
base=Path('/opt/zeekr-control')
with (base/'.deploy.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    r=json.loads((base/'.release-ready.json').read_text())
    assert str((base/'current').resolve())==r['candidate']
    import importlib.util
    spec=importlib.util.spec_from_file_location('release_workflow',base/'.release-workflow.py');workflow=importlib.util.module_from_spec(spec);spec.loader.exec_module(workflow)
    installed=Path('/etc/systemd/system/zeekr-reports.service').is_file()
    services=['zeekr-control','zeekr-monitor']+(['zeekr-reports'] if installed else [])
    subprocess.run(['systemctl','stop',*services],check=True)
    temp=base/'.current-release-rollback'
    assert not temp.exists() and not temp.is_symlink()
    temp.symlink_to(r['previous']);os.replace(temp,base/'current')
    subprocess.run(['systemctl','start',*workflow.runtime_services(r['previous'],installed)],check=True)
    print('ROLLBACK_APPLIED',r['previous'])
