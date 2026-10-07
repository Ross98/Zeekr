import hashlib,json,subprocess,time,urllib.request,urllib.error
from pathlib import Path
base=Path('/opt/zeekr-control');record=json.loads((base/'.release-ready.json').read_text());active=(base/'current').resolve()
assert str(active)==record['candidate']
baseline=json.loads((base/'.release-baseline.json').read_text());changes=json.loads((base/'.release-changes.json').read_text())
for name,value in record['candidate_hashes'].items():assert hashlib.sha256((active/name).read_bytes()).hexdigest()==value,'Deployed hash mismatch'
for name,value in baseline['manifest'].items():
 if name not in changes and name!='release-manifest.json':assert hashlib.sha256((active/name).read_bytes()).hexdigest()==value,'Unrelated deployed file changed'
print('DEPLOYED_HASHES_PASS',len(changes))
import importlib.util
spec=importlib.util.spec_from_file_location('release_workflow',base/'.release-workflow.py');workflow=importlib.util.module_from_spec(spec);spec.loader.exec_module(workflow)
for service in [*workflow.runtime_services(active),'nginx']:
 values={line.split('=',1)[0]:line.split('=',1)[1] for line in subprocess.check_output(['systemctl','show',service,'-p','ActiveState','-p','SubState','-p','NRestarts','-p','MainPID'],text=True).splitlines()}
 assert values['ActiveState']=='active' and values['SubState']=='running' and values['NRestarts']=='0'
 if service!='nginx':assert Path('/proc/'+values['MainPID']+'/cwd').resolve()==active,'Wrong process release'
 print('SERVICE_PASS',service,'NRestarts=0')
for attempt in range(20):
 try:
  with urllib.request.urlopen('http://127.0.0.1:18765/',timeout=2) as response:
   if response.status==200:break
 except (urllib.error.URLError,TimeoutError):time.sleep(.5)
else:raise AssertionError('Web did not become ready')
extra_routes=[('/'+Path(name).name,401) for name in changes if name.startswith('zeekr_control/static/') and Path(name).suffix in {'.webp','.png','.svg'}]
for route,expected in extra_routes+[('/',200),('/theme.css',200),('/login.js',200),('/login.css',200),('/api/location',401),('/api/insights/report',401),('/api/insights/calendar',401),('/app.js',401),('/app.css',401),('/car-001-top.png',401),('/overview-dashboard.js',401)]:
 try:
  with urllib.request.urlopen('http://127.0.0.1:18765'+route,timeout=5) as response:code=response.status
 except urllib.error.HTTPError as response:code=response.code
 assert code==expected,(route,code)
 print('HTTP_PASS',route,code)
subprocess.run(['sudo','-u','zeekr-control','env','HOME=/var/lib/zeekr-control','python3',str(base/'check-release.py'),str(active),'--require-image','--service-user','zeekr-control'],check=True)
logs=subprocess.check_output(['journalctl','-u','zeekr-control','--since','2 minutes ago','--no-pager','-o','cat'],text=True)
assert 'Traceback (most recent call last)' not in logs,'New Web traceback'
import sqlite3,os
store=Path('/var/lib/zeekr-control/Library/Application Support/ZeekrControl/web-remembered.sqlite3')
info=store.stat();assert info.st_mode & 0o777==0o600
owner=subprocess.check_output(['id','-u','zeekr-control'],text=True).strip();assert info.st_uid==int(owner)
assert store.parent.stat().st_mode & 0o777==0o700
with sqlite3.connect('file:'+str(store)+'?mode=ro',uri=True) as connection:
 columns=[row[1] for row in connection.execute('PRAGMA table_info(remembered_sessions)')]
 assert columns==['token_key','password_key','client_key','expires']
 assert connection.execute('PRAGMA quick_check').fetchone()==('ok',)
print('PRODUCTION_PRIVATE_REMEMBERED_STORE_PASS owner/mode/schema')

import sys
sys.path.insert(0,str(active))
from zeekr_control.release_info import read_release
release=read_release(active)
assert release['base_version']==record['commit'] and all(row['status']=='matched' for row in release['features'])
backup=Path(record['backup'])
roads=store.parent/'road-networks'
if roads.exists():
 assert roads.stat().st_mode & 0o777==0o700 and roads.stat().st_uid==int(owner)
 old_roads=backup/'Library/Application Support/ZeekrControl/road-networks'
 assert {p.name for p in roads.glob('*.sqlite3')}=={p.name for p in old_roads.glob('*.sqlite3')}
 for path in roads.glob('*.sqlite3'):
  assert path.stat().st_mode & 0o777==0o600 and path.stat().st_uid==int(owner)
  assert hashlib.sha256(path.read_bytes()).digest()==hashlib.sha256((old_roads/path.name).read_bytes()).digest()
  with sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True) as connection:
   assert connection.execute('PRAGMA quick_check').fetchone()==('ok',)
 print('PRODUCTION_ROAD_DATABASES_PASS hashes/owner/mode/quick_check')
old=sqlite3.connect('file:'+str(backup/'Library/Application Support/ZeekrControl/tracks.sqlite3')+'?mode=ro',uri=True)
new=sqlite3.connect('file:/var/lib/zeekr-control/Library/Application Support/ZeekrControl/tracks.sqlite3?mode=ro',uri=True)
try:
 names=['id','vehicle','kind','summary','message','delivery','attempts','sent_at'];query='SELECT '+','.join(names)+" FROM monitor_events WHERE delivery='sent'"
 rows=old.execute(query).fetchall()
 for row in rows:
  assert new.execute('SELECT '+','.join(names)+' FROM monitor_events WHERE id=?',(row[0],)).fetchone()==row,'Sent event changed'
 print('SENT_EVENT_PRESERVATION_PASS',len(rows))
 columns=[r[1] for r in old.execute('PRAGMA table_info(monitor_event_media)')]
 query='SELECT '+','.join(columns)+" FROM monitor_event_media WHERE delivery='sent'"
 media=old.execute(query).fetchall()
 for row in media:
  assert new.execute('SELECT '+','.join(columns)+' FROM monitor_event_media WHERE event_id=?',(row[columns.index('event_id')],)).fetchone()==row,'Sent media changed'
 print('SENT_MEDIA_PRESERVATION_PASS',len(media))
finally:old.close();new.close()
print('POST_DEPLOY_PASS')
