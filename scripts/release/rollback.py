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
    if (Path(r['candidate'])/'zeekr_control/delivery_state.py').is_file():
     subprocess.run(['sudo','-u','zeekr-control','env','HOME=/var/lib/zeekr-control','PYTHONDONTWRITEBYTECODE=1','/usr/bin/python3','-c',"import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from zeekr_control.delivery_state import normalize_preparation_for_rollback; print('DELIVERY_ROLLBACK_NORMALIZED',normalize_preparation_for_rollback(Path('/var/lib/zeekr-control/Library/Application Support/ZeekrControl')))",r['candidate']],check=True)
    temp=base/'.current-release-rollback'
    assert not temp.exists() and not temp.is_symlink()
    temp.symlink_to(r['previous']);os.replace(temp,base/'current')
    subprocess.run(['systemctl','start',*workflow.runtime_services(r['previous'],installed)],check=True)
    print('ROLLBACK_APPLIED',r['previous'])
