import fcntl,json,os,subprocess
from pathlib import Path
base=Path('/opt/zeekr-control')
with (base/'.deploy.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    r=json.loads((base/'.release-ready.json').read_text())
    assert str((base/'current').resolve())==r['candidate']
    subprocess.run(['systemctl','stop','zeekr-control','zeekr-monitor'],check=True)
    temp=base/'.current-release-rollback'
    assert not temp.exists() and not temp.is_symlink()
    temp.symlink_to(r['previous']);os.replace(temp,base/'current')
    subprocess.run(['systemctl','start','zeekr-monitor','zeekr-control'],check=True)
    print('ROLLBACK_APPLIED',r['previous'])
