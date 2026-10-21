"""Local macOS release adapter. Import/inspect/prepare never restart services.

Keep Linux transport unchanged. All mutations require an explicit subcommand.
"""
import argparse
from contextlib import closing, contextmanager
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import uuid

import workflow

LABELS = ('local.zeekr.web', 'local.zeekr.monitor', 'local.zeekr.reports')
RESOURCE_LABEL = 'local.zeekr.resources'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def release_name(value):
    require(bool(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]*', value)), 'Invalid release name')
    return value


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.release-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, indent=2); out.write('\n'); out.flush(); os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):os.unlink(name)


def digest(path):
    with Path(path).open('rb') as stream:
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024*1024), b''):h.update(block)
        return h.hexdigest()


def public_hashes(root):
    names = workflow.inputs(root)
    if (Path(root)/'release-manifest.json').exists():names.append('release-manifest.json')
    return {name:digest(Path(root)/name) for name in names}


def check_hashes(root, expected):
    require(public_hashes(root) == expected, 'Public input inventory or hashes changed')


def check_paths(host, record):
    for key, parent in [('candidate','releases'), ('previous','releases'), ('backup','backups')]:
        path = Path(record[key])
        require(path.parent == host.base/parent and path.resolve().parent == host.base/parent,
                'Release path escapes host: '+key)
        release_name(path.name)
    require(record['candidate'] != record['previous'], 'Candidate must differ from active release')


def job_fields(text):
    return dict(re.findall(r'^\t(state|pid|runs) = ([^\n]+)$', text, re.MULTILINE))


class Host:
    def __init__(self, base=None):
        self.base = Path(base or Path.home()/'Library/Application Support/ZeekrServer').resolve()
        self.agents = Path.home()/'Library/LaunchAgents'
        self.domain = 'gui/'+str(os.getuid())
        self.refresh()

    def refresh(self):
        self.configs = {}
        labels = list(LABELS)
        resource = self.agents/(RESOURCE_LABEL+'.plist')
        if resource.exists() or resource.is_symlink():labels.append(RESOURCE_LABEL)
        for label in labels:
            path = self.agents/(label+'.plist')
            require(path.is_file() and not path.is_symlink() and path.stat().st_uid == os.getuid(),
                    'Missing or unsafe launch agent: '+label)
            config = plistlib.loads(path.read_bytes())
            require(config.get('Label') == label and
                    Path(config['WorkingDirectory']) == self.base/'current' and
                    Path(config['EnvironmentVariables']['HOME']) == self.base/'state',
                    'Launch agent layout differs: '+label)
            require(config['ProgramArguments'][:4] == ['/usr/bin/caffeinate','-s','/usr/bin/python3','-m'],
                    'Unsupported launch agent runtime')
            expected = (['zeekr_control','web','--port','18765'] if label.endswith('.web') else
                        ['zeekr_control','monitor'] if label.endswith('.monitor') else
                        ['zeekr_control.resource_monitor'] if label == RESOURCE_LABEL else
                        ['zeekr_control.periodic_schedule'])
            require(config['ProgramArguments'][4:] == expected, 'Unexpected service command')
            self.configs[label] = config
        self.environment = dict(self.configs[LABELS[0]]['EnvironmentVariables'])
        require(self.environment.get('ZEEKR_AUTH_FILE') == str(self.base/'state/web-auth.json'),
                'Unexpected authentication file')
        self.origin = self.environment.get('ZEEKR_PUBLIC_ORIGIN', '')
        from urllib.parse import urlsplit
        url = urlsplit(self.origin)
        require(url.scheme == 'https' and bool(url.hostname) and not url.path and
                not url.username and not url.password and not url.query and not url.fragment,
                'Expected dedicated HTTPS origin')
        self.python = '/usr/bin/python3'
        self.home = self.base/'state'
        self.data = self.home/'Library/Application Support/ZeekrControl'
        for p, mode in [(self.home,0o700), (self.data,0o700), (self.home/'web-auth.json',0o600)]:
            require(p.exists() and not p.is_symlink() and p.stat().st_uid == os.getuid() and
                    p.stat().st_mode & 0o777 == mode, 'Unsafe runtime state owner/mode')

    def signature(self):
        return {label:digest(self.agents/(label+'.plist')) for label in self.configs}

    def job(self, label):
        result = subprocess.run(['launchctl','print',self.domain+'/'+label], capture_output=True, text=True)
        return job_fields(result.stdout) if result.returncode == 0 else None

    def active(self):
        require((self.base/'current').is_symlink(), 'current must be a release symlink')
        path = (self.base/'current').resolve()
        require(path.parent == self.base/'releases', 'Unexpected active release')
        return path

    def runtime_environment(self):
        env = dict(os.environ)
        env.update(self.environment)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        return env

    def run(self, command, cwd=None, capture=False):
        return subprocess.run(command, cwd=cwd, env=self.runtime_environment(), check=True,
                              capture_output=capture, text=True)

    def stop(self):
        # Track children as well: caffeinate is launchd's main PID, Python is its child.
        pairs = [tuple(map(int, line.split())) for line in
                 subprocess.check_output(['ps','-axo','pid=,ppid='], text=True).splitlines()]
        tracked = {int(j['pid']) for label in self.configs for j in [self.job(label)] if j and 'pid' in j}
        while True:
            children = {pid for pid, parent in pairs if parent in tracked}
            if children <= tracked:break
            tracked |= children
        for label in self.configs:
            if self.job(label) is not None:
                subprocess.run(['launchctl','bootout',self.domain+'/'+label], check=True)
        deadline = time.monotonic()+90
        while True:
            alive = []
            for pid in tracked:
                try:os.kill(pid,0);alive.append(pid)
                except ProcessLookupError:pass
            if not alive:
                # A worker may have spawned after the initial process snapshot.
                result = subprocess.run(['/usr/sbin/lsof','-n','-d','cwd','-Fn'],
                                        capture_output=True,text=True)
                require(result.returncode == 0, 'Unable to verify remaining service processes')
                require('n'+str(self.active()) not in result.stdout.splitlines(),
                        'A process still uses the active release; no backup or cutover')
                return
            require(time.monotonic() < deadline, 'Service descendants still running; no backup or cutover')
            time.sleep(.2)

    def start(self):
        for label in self.configs:
            if self.job(label) is None:
                subprocess.run(['launchctl','bootstrap',self.domain,str(self.agents/(label+'.plist'))],check=True)

    def health(self, fresh=False):
        deadline = time.monotonic()+20
        while True:
            if all((self.job(label) or {}).get('state') == 'running' for label in self.configs):break
            require(time.monotonic() < deadline, 'launchd services did not start')
            time.sleep(.2)
        for label in self.configs:
            info = self.job(label)
            if fresh:require(info.get('runs') == '1', 'Service restarted unexpectedly: '+label)
            pid = info['pid']
            result = subprocess.run(['/usr/sbin/lsof','-a','-p',pid,'-d','cwd','-Fn'],
                                    capture_output=True,text=True,check=True)
            require('n'+str(self.active()) in result.stdout.splitlines(), 'Process has wrong release: '+label)
        if RESOURCE_LABEL in self.configs:
            deadline = time.monotonic()+15
            while True:
                try:state=json.loads(read(self.data/'resource-health.json')['state'])
                except (OSError,ValueError,KeyError):state={}
                if (state.get('monitor_pid') == int(self.job(RESOURCE_LABEL)['pid']) and
                        0 <= time.time()-state.get('checked_at',0) < 180):break
                require(time.monotonic() < deadline, 'Resource monitor heartbeat unavailable')
                time.sleep(.2)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for base in ('http://127.0.0.1:18765', self.origin):
            for route, expected in [('/',200),('/api/state',401),('/app.js',401)]:
                deadline = time.monotonic()+10
                while True:
                    try:
                        with opener.open(base+route, timeout=3) as response:code=response.status
                    except urllib.error.HTTPError as exc:code=exc.code
                    except (OSError,urllib.error.URLError):code=0
                    if code == expected:break
                    require(time.monotonic() < deadline, 'Service HTTP/authentication gate failed')
                    time.sleep(.2)

    def artwork(self, root):
        self.run([self.python, str(root/'zeekr_control/release_check.py'), str(root),
                  '--require-image','--service-user',getpass.getuser()])


@contextmanager
def lock(host):
    with (host.base/'migration.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def overlay(archive_path, candidate, changes):
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        require(len(members) == len(changes) and {m.name for m in members} == set(changes),
                'Overlay file inventory differs')
        for member in members:
            workflow.allowed(member.name)
            target = candidate/member.name
            require(member.isfile() and not target.is_symlink() and candidate.resolve() in target.resolve().parents,
                    'Unsafe overlay entry')
            require(hashlib.sha256(archive.extractfile(member).read()).hexdigest() == changes[member.name],
                    'Overlay hash differs')
        for member in members:
            target = candidate/member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
            target.write_bytes(archive.extractfile(member).read());target.chmod(mode)


def backup_state(source, destination):
    require(not destination.exists(), 'Backup already exists')
    entries = [source, *source.rglob('*')]
    require(all(not p.is_symlink() and (p.is_file() or p.is_dir()) for p in entries), 'Unsafe state entry')
    size = sum(p.stat().st_size for p in entries if p.is_file())
    require(shutil.disk_usage(destination.parent).free > size+256*1024*1024, 'Insufficient backup space')
    shutil.copytree(source,destination)
    for path in entries:
        copied = destination/path.relative_to(source)
        a,b = path.stat(),copied.stat()
        require((a.st_uid,a.st_gid,a.st_mode & 0o777) == (b.st_uid,b.st_gid,b.st_mode & 0o777),
                'Backup metadata differs')
        if path.is_file():require(digest(path) == digest(copied), 'Backup contents differ')
    check_databases(destination)


def check_databases(root):
    for path in root.rglob('*.sqlite3'):
        require(path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o777 == 0o600,
                'Unsafe database owner/mode')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            require(db.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'Database integrity failure')


def prepare(host, args):
    output = Path(args.output).resolve()
    require(not output.exists() and host.base not in output.parents, 'Use fresh output outside runtime tree')
    name = release_name(args.name)
    active = host.active()
    baseline = dict(active=str(active), manifest=public_hashes(active), agents=host.signature())
    output.mkdir(parents=True)
    staged = output/'staged';staged.mkdir()
    for name_in, sha in baseline['manifest'].items():
        target=staged/name_in;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(active/name_in,target)
    paths = read(args.paths)
    require(isinstance(paths,list) and all(isinstance(n,str) for n in paths), 'Expected explicit paths array')
    for path in paths:
        workflow.allowed(path)
        data = subprocess.check_output(['git','show',args.commit+':'+path],cwd=Path(__file__).resolve().parents[2])
        target=staged/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    check_hashes(active,baseline['manifest'])
    require(host.signature() == baseline['agents'], 'Launch agents changed during preparation')
    write(output/'baseline.json',baseline)
    workflow.build(staged,output/'baseline.json',args.commit,str(active),str(host.base/'releases'/name),
                   str(host.base/'backups'/name),paths,read(args.checks),output/'bundle')
    print('MACOS_BUNDLE_READY',output/'bundle')


def stage(host, bundle, tailscale_ip=False, resource_monitor=False):
    ready=bundle/'.mini-ready.json'
    if ready.exists():ready.unlink()
    config=read(bundle/'.release-config.json');check_paths(host,config)
    baseline=read(bundle/'.release-baseline.json');changes=read(bundle/'.release-changes.json')
    require(str(host.active()) == baseline['active'] == config['previous'], 'Active release changed')
    require(host.signature() == baseline['agents'], 'Launch agents changed')
    check_hashes(host.active(),baseline['manifest'])
    candidate=Path(config['candidate'])
    require(not candidate.exists() and shutil.disk_usage(host.base).free > 1024**3, 'Candidate exists or disk is full')
    shutil.copytree(host.active(),candidate,symlinks=True)
    overlay(bundle/'.release-changes.tar',candidate,changes)
    for name,sha in baseline['manifest'].items():
        if name not in changes:require(digest(candidate/name) == sha,'Unrelated candidate change')
    if tailscale_ip:
        # Check the candidate API before changing any launch agent.
        host.run([host.python,'-c',
                  "from types import SimpleNamespace; from zeekr_control.web import make_server; s=make_server(SimpleNamespace(),0,tailscale_proxy=True); s.server_close()"],cwd=candidate)
    if resource_monitor or RESOURCE_LABEL in baseline['agents']:
        host.run([host.python,'-m','zeekr_control.resource_monitor','--help'],cwd=candidate,capture=True)
    code = ("from pathlib import Path; from zeekr_control.release_info import FEATURES,write_manifest,read_release; "
            "import sys,json; root=Path.cwd(); old=read_release(Path(sys.argv[2])); "
            "keys=[f['id'] for f in old['features']] if old['status']=='recorded' else list(FEATURES); "
            "write_manifest(root,sys.argv[1],keys); print(json.dumps(read_release(root)))")
    metadata=json.loads(host.run([host.python,'-c',code,config['commit'],config['previous']],cwd=candidate,capture=True).stdout)
    require(metadata['status'] == 'recorded' and all(f['status']=='matched' for f in metadata['features']),
            'Feature manifest failed')
    host.artwork(candidate)
    tier=workflow.risk(list(changes));require(tier == config['risk'],'Risk mismatch')
    if tier == 'ui':
        receipt=read(bundle/'.release-receipt.json')
        require(receipt['passed'] and workflow.browser_checks(receipt['commands']), 'Missing desktop browser checks')
        # Manifest is release metadata, not an executable validation input.
        require({n:digest(candidate/n) for n in workflow.inputs(candidate)} == receipt['hashes'],
                'Desktop validation inputs differ')
    else:
        # This CLI runs as exactly the user in the launch agents, without sudo.
        env=dict(os.environ);os.environ.update(host.environment);os.environ['PYTHONDONTWRITEBYTECODE']='1'
        try:
            workflow.validate(candidate,workflow.inputs(candidate),[[host.python,'-m','unittest','discover','-s','tests']],
                              bundle/'macos-validation.json',context='macos-service-user-candidate')
        finally:os.environ.clear();os.environ.update(env)
    record=dict(config,baseline=baseline,candidate_hashes=public_hashes(candidate),tailscale_ip=tailscale_ip,
                resource_monitor=resource_monitor)
    write(bundle/'.mini-ready.json',record)
    print('MACOS_CANDIDATE_READY')


def preflight(host, record):
    check_paths(host,record)
    require(str(host.active()) == record['previous'], 'Active release changed')
    require(host.signature() == record['baseline']['agents'], 'Launch agents changed')
    check_hashes(host.active(),record['baseline']['manifest'])
    check_hashes(Path(record['candidate']),record['candidate_hashes'])
    require(not Path(record['backup']).exists(), 'Backup already exists')
    host.health()


def switch(link, target):
    temporary=link.with_name('.current-'+uuid.uuid4().hex)
    try:
        temporary.symlink_to(target);os.replace(temporary,link)
    finally:
        if temporary.is_symlink():temporary.unlink()


def resource_agent(host):
    config=plistlib.loads(plistlib.dumps(host.configs[LABELS[1]]))
    config.update(Label=RESOURCE_LABEL,WorkingDirectory=str(host.base/'current'),
                  ProgramArguments=['/usr/bin/caffeinate','-s','/usr/bin/python3','-m','zeekr_control.resource_monitor'],
                  RunAtLoad=True,KeepAlive={'SuccessfulExit':False},Nice=10,ThrottleInterval=30,
                  StandardOutPath=str(host.base/'logs/resources.stdout.log'),
                  StandardErrorPath=str(host.base/'logs/resources.stderr.log'))
    return config


def write_agent(path, config):
    require(not path.is_symlink(),'Launch agent symlink rejected')
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.zeekr-')
    try:
        with os.fdopen(fd,'wb') as stream:plistlib.dump(config,stream)
        os.chmod(name,path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def restore_agents(agents, saved):
    for label in LABELS:require((saved/(label+'.plist')).is_file(),'Incomplete launch agent backup')
    for label in (*LABELS,RESOURCE_LABEL):
        source=saved/(label+'.plist');target=agents/(label+'.plist')
        require(not target.is_symlink(),'Launch agent symlink rejected')
        if source.is_file():shutil.copy2(source,target)
        elif label == RESOURCE_LABEL and target.exists():target.unlink()


def cutover(host, record):
    host.stop()
    backup=Path(record['backup']);backup.mkdir(mode=0o700)
    backup_state(host.home,backup/'state')
    agents=backup/'agents';agents.mkdir(mode=0o700)
    for label in host.configs:
        shutil.copy2(host.agents/(label+'.plist'),agents/(label+'.plist'))
    (backup/'agents-complete').touch(mode=0o600)
    if record.get('tailscale_ip'):
        p=host.agents/(LABELS[0]+'.plist');config=plistlib.loads(p.read_bytes())
        config['EnvironmentVariables'].pop('ZEEKR_TRUST_PROXY_IP',None)
        config['EnvironmentVariables']['ZEEKR_TRUST_TAILSCALE_IP']='1'
        write_agent(p,config)
    if record.get('resource_monitor'):
        write_agent(host.agents/(RESOURCE_LABEL+'.plist'),resource_agent(host))
    switch(host.base/'current',Path(record['candidate']))
    host.refresh();host.start()


def preserved_sent_records(backup_data, data):
    old_path=backup_data/'tracks.sqlite3';new_path=data/'tracks.sqlite3'
    require(old_path.is_file() and new_path.is_file(),'Missing event database')
    with closing(sqlite3.connect(old_path.as_uri()+'?mode=ro',uri=True)) as old, \
         closing(sqlite3.connect(new_path.as_uri()+'?mode=ro',uri=True)) as new:
        for table,key in [('monitor_events','id'),('monitor_event_media','event_id')]:
            columns=[r[1] for r in old.execute('PRAGMA table_info('+table+')')]
            require(columns and columns == [r[1] for r in new.execute('PRAGMA table_info('+table+')')],
                    'Event schema changed; preservation requires explicit migration review')
            for row in old.execute("SELECT * FROM "+table+" WHERE delivery='sent'"):
                require(new.execute('SELECT * FROM '+table+' WHERE '+key+'=?',(row[columns.index(key)],)).fetchone() == row,
                        'Sent event/media changed')



def verify_private_state(backup, current):
    # Authentication/session files are stable across a code release. Compare only
    # digests; never include private content in an exception or release receipt.
    for relative in ('web-auth.json','Library/Application Support/ZeekrControl/session.json'):
        old=backup/relative;new=current/relative
        require(old.is_file() and new.is_file() and digest(old)==digest(new),
                'Authentication or vehicle session changed during release')
    data=Path('Library/Application Support/ZeekrControl')
    for filename,table,keys in [('personal.sqlite3','records',('owner','vehicle','collection','id')),
                                ('web-remembered.sqlite3','remembered_sessions',('token_key',))]:
        old_path=backup/data/filename;new_path=current/data/filename
        if not old_path.exists():continue
        require(new_path.is_file(),'Persistent private database disappeared')
        with closing(sqlite3.connect(old_path.as_uri()+'?mode=ro',uri=True)) as old, \
             closing(sqlite3.connect(new_path.as_uri()+'?mode=ro',uri=True)) as new:
            columns=[row[1] for row in old.execute('PRAGMA table_info('+table+')')]
            require(columns and set(columns) <= {row[1] for row in new.execute('PRAGMA table_info('+table+')')},
                    'Private table schema no longer compatible')
            select=','.join(columns);where=' AND '.join(key+'=?' for key in keys)
            for row in old.execute('SELECT '+select+' FROM '+table):
                if table=='remembered_sessions' and row[columns.index('expires')] <= time.time():continue
                key=tuple(row[columns.index(name)] for name in keys)
                require(new.execute('SELECT '+select+' FROM '+table+' WHERE '+where,key).fetchone()==row,
                        'Existing personal record or remembered credential changed')
    old_roads=backup/data/'road-networks';new_roads=current/data/'road-networks'
    if old_roads.exists():
        for old in old_roads.glob('*.sqlite3'):
            require((new_roads/old.name).is_file() and digest(old)==digest(new_roads/old.name),
                    'Existing road database changed')


def verify(host, record):
    require(str(host.active()) == record['candidate'], 'Wrong active release')
    check_hashes(host.active(),record['candidate_hashes'])
    host.health(fresh=True);host.artwork(host.active());check_databases(host.home)
    require((host.data/'web-remembered.sqlite3').is_file(),'Remembered login database missing')
    preserved_sent_records(Path(record['backup'])/'state/Library/Application Support/ZeekrControl',host.data)
    verify_private_state(Path(record['backup'])/'state',host.home)
    print('MACOS_SERVICE_AUTH_HASH_ARTWORK_DATA_PASS')


def rollback(host, record):
    check_paths(host,record)
    require(str(host.active()) in (record['candidate'],record['previous']), 'Unrelated release is active')
    check_hashes(Path(record['previous']),record['baseline']['manifest'])
    host.stop()
    candidate=Path(record['candidate'])
    if str(host.active()) == record['candidate'] and (candidate/'zeekr_control/delivery_state.py').is_file():
        check_hashes(candidate,record['candidate_hashes'])
        host.run([host.python,'-c',
                  'from pathlib import Path; from zeekr_control.delivery_state import normalize_preparation_for_rollback; '
                  'import sys; normalize_preparation_for_rollback(Path(sys.argv[1]))',str(host.data)],cwd=candidate)
    saved=Path(record['backup'])/'agents'
    if (Path(record['backup'])/'agents-complete').is_file():
        restore_agents(host.agents,saved)
    switch(host.base/'current',Path(record['previous']))
    host.refresh();host.start();host.health(fresh=True);host.artwork(host.active())
    print('MACOS_ROLLBACK_PASS; latest business state retained')


def deploy(host, record):
    preflight(host,record)  # Drift must fail before any service stops.
    write(host.base/'.macos-release.json',record)
    started=time.monotonic()
    try:
        cutover(host,record);verify(host,record)
    except BaseException:
        rollback(host,record)
        raise
    finally:
        with (host.base/'.release-timings.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(platform='macos',phase='deploy',seconds=round(time.monotonic()-started,3)))+'\n')


def inspect(host):
    return dict(platform='macos',active=str(host.active()),base=str(host.base),
                state=str(host.home),origin=host.origin,
                services={label:host.job(label) for label in host.configs},
                starts_at='user login',tailscale_ip=host.environment.get('ZEEKR_TRUST_TAILSCALE_IP')=='1')


def change_password(host):
    require(sys.stdin.isatty(), 'Run password change in an interactive terminal')
    first=getpass.getpass('新网页密码（16–256 字符）：');second=getpass.getpass('再次输入：')
    require(16 <= len(first) <= 256 and first == second, 'Invalid or mismatched password; unchanged')
    # Password goes through stdin to production helpers, never argv or logs.
    env=host.runtime_environment()
    code=('import sys; from pathlib import Path; from zeekr_control.auth import password_record; '
          'from zeekr_control.storage import save; save(Path(sys.argv[1]),password_record(sys.stdin.read()))')
    subprocess.run([host.python,'-c',code,str(host.home/'web-auth.json')],input=first,text=True,
                   cwd=host.active(),env=env,check=True)
    # Only the Web service needs restart. Collection and reports stay running.
    try:
        subprocess.run(['launchctl','kickstart','-k',host.domain+'/'+LABELS[0]],check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError('密码文件已更新，但网页服务重启失败；修复服务后请使用新密码登录。') from error
    print('密码已更新并请求重启网页服务；请用新密码登录。')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path)
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('inspect')
    p=sub.add_parser('prepare')
    for name in ('commit','paths','checks','output','name'):p.add_argument('--'+name,required=True)
    for action in ('stage','deploy'):
        p=sub.add_parser(action);p.add_argument('--bundle',type=Path,required=True)
        if action=='stage':
            p.add_argument('--tailscale-ip',action='store_true')
            p.add_argument('--resource-monitor',action='store_true')
    sub.add_parser('verify');sub.add_parser('rollback');sub.add_parser('password')
    args=parser.parse_args(argv)
    require(sys.platform == 'darwin' and os.geteuid() != 0,'Run locally on macOS as the launch agent user, without sudo')
    host=Host(args.base)
    if args.action=='inspect':print(json.dumps(inspect(host),ensure_ascii=False,indent=2));return
    with lock(host):
        if args.action=='prepare':prepare(host,args)
        elif args.action=='stage':stage(host,args.bundle.resolve(),args.tailscale_ip,args.resource_monitor)
        elif args.action=='deploy':deploy(host,read(args.bundle/'.mini-ready.json'))
        elif args.action=='verify':verify(host,read(host.base/'.macos-release.json'))
        elif args.action=='rollback':rollback(host,read(host.base/'.macos-release.json'))
        else:change_password(host)


if __name__=='__main__':main()
