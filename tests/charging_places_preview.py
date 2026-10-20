"""Run local charging-place acceptance against a private historical copy.

Never connects to a vehicle or writes the source snapshot/production database.
All interactive corrections affect only this process's temporary SQLite files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from insights_fixture import seed
from zeekr_control.web import App,make_server
from zeekr_control.storage import save
from zeekr_control.monitor import Monitor
from zeekr_control.personal_store import account_scope
from zeekr_control.commute_tags import CommuteTags


def populate(app,session,snapshot):
    vehicle=hashlib.sha256(b'insights-fixture-car').hexdigest();owner=account_scope(session)
    seed(app,session)
    app.profile=dict(name='历史数据验收副本',variant='仅本地副本；修改不影响线上',battery_capacity_kwh=86,image='',image_alt='')
    monitor=Monitor(app.database_path)
    with monitor.tracks.connect() as db:
        for row in snapshot['events']:
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                       (row['id'],vehicle,row['kind'],json.dumps(row['summary']), '',row['created']))
        for index,(stamp,observed,gap,location) in enumerate(snapshot['observations']):
            db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',(vehicle,'preview-'+str(index),stamp,observed,gap,location))
        for stamp,observed,payload,decoder in snapshot['reports']:
            db.execute('INSERT OR IGNORE INTO report_observations VALUES(?,?,?,?,?)',(vehicle,stamp,observed,payload,decoder))
        for key,table in [('hidden_charges','charge_record_trash'),('hidden_trips','trip_record_trash')]:
            db.execute('CREATE TABLE IF NOT EXISTS '+table+' (vehicle TEXT,event_id TEXT,removed_at INTEGER,PRIMARY KEY(vehicle,event_id))')
            for identity in snapshot[key]:db.execute('INSERT INTO '+table+' VALUES(?,?,?)',(vehicle,identity,snapshot['exported_at']))
    for collection,records in snapshot['collections'].items():
        revision=0
        for row in reversed(records):
            app.personal_store.change(owner,vehicle,collection,'save',row['id'],row['body'],revision);revision+=1
            if row['deleted']:
                app.personal_store.change(owner,vehicle,collection,'delete',row['id'],None,revision);revision+=1
    rule=snapshot.get('commute',{})
    if rule.get('home') and rule.get('work') and not rule.get('deleted'):
        CommuteTags(app.personal_store,app.database_path).update(owner,vehicle,dict(action='commute-save',revision=0,home=rule['home'],work=rule['work']))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--snapshot',type=Path,required=True);parser.add_argument('--port',type=int,default=18766);args=parser.parse_args()
    snapshot=json.loads(args.snapshot.read_text())
    with tempfile.TemporaryDirectory(prefix='zeekr-charging-acceptance-') as directory:
        session_path=Path(directory)/'private/session.json';session={'accessToken':'LOCAL-ACCEPTANCE-COPY-ONLY'};save(session_path,session)
        def forbidden(_):raise AssertionError('Vehicle access is disabled in the local acceptance copy')
        app=App(session_path,client_factory=forbidden)
        try:
            populate(app,session,snapshot);server=make_server(app,args.port)
            print('LOCAL_ACCEPTANCE_READY http://127.0.0.1:%d/'%server.server_port,flush=True)
            try:server.serve_forever()
            except KeyboardInterrupt:pass
            finally:server.server_close()
        finally:app.close()
