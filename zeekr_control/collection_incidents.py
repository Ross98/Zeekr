"""Independent outage ledger, without secrets, coordinates or inferred coverage."""
from contextlib import contextmanager
import uuid
from .private_state import database


class CollectionIncidents:
    def __init__(self,root):self.root=root

    @contextmanager
    def connect(self):
        with database(self.root/'collection-incidents.sqlite3') as db:
            db.execute('CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY,owner TEXT,vehicle TEXT,scope TEXT,opened_at INTEGER,last_failure INTEGER,attempts INTEGER,baseline INTEGER,last_success INTEGER,refresh_completed_at INTEGER,interface_recovered_at INTEGER,fresh_state_seen_at INTEGER,fresh_vehicle_state_at INTEGER,fresh_state_outcome TEXT,classification TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS incidents_owner ON incidents(owner,vehicle,opened_at)')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS incident_open ON incidents(owner,vehicle) WHERE interface_recovered_at IS NULL')
            db.execute('CREATE TABLE IF NOT EXISTS probes (incident_id TEXT,at INTEGER,scope TEXT,kind TEXT)')
            db.commit()
            yield db

    def failure(self,owner,vehicle,scope,now,baseline=None,last_success=None):
        with self.connect() as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM incidents WHERE owner=? AND vehicle=? AND interface_recovered_at IS NULL',(owner,vehicle)).fetchone()
            if row:
                db.execute('UPDATE incidents SET last_failure=?,attempts=attempts+1 WHERE id=?',(now,row['id']))
                identity=row['id']
            else:
                db.execute("UPDATE incidents SET fresh_state_outcome='not_observed_before_next_outage' WHERE owner=? AND vehicle=? AND interface_recovered_at IS NOT NULL AND fresh_state_outcome='waiting'",(owner,vehicle))
                identity=uuid.uuid4().hex
                db.execute("INSERT INTO incidents VALUES(?,?,?,?,?,?,1,?,?,NULL,NULL,NULL,NULL,'waiting','unclassified')",(identity,owner,vehicle,scope,now,now,baseline,last_success))
            db.execute('INSERT INTO probes VALUES(?,?,?,?)',(identity,now,scope,'1509'))
            return dict(db.execute('SELECT * FROM incidents WHERE id=?',(identity,)).fetchone())

    def current(self,owner,vehicle):
        with self.connect() as db:
            row=db.execute('SELECT * FROM incidents WHERE owner=? AND vehicle=? AND interface_recovered_at IS NULL',(owner,vehicle)).fetchone()
            return dict(row) if row else None

    def read(self,identity):
        with self.connect() as db:
            row=db.execute('SELECT * FROM incidents WHERE id=?',(identity,)).fetchone()
            return dict(row) if row else None

    def classify(self,identity,classification,now):
        allowed={'refreshed','manual_required','uncertain','rate_limited','storage_error'}
        if classification not in allowed:raise ValueError('未知中断分类。')
        with self.connect() as db,db:
            db.execute('UPDATE incidents SET classification=? WHERE id=?',(classification,identity))
            if classification=='refreshed':db.execute('UPDATE incidents SET refresh_completed_at=? WHERE id=?',(now,identity))
            db.execute('INSERT INTO probes VALUES(?,?,?,?)',(identity,now,'',classification))

    def success(self,owner,vehicle,scope,outcome,now,vehicle_state):
        if not (outcome and outcome.operation=='status' and outcome.actual_request and not outcome.cache_hit
                and outcome.schema_valid and outcome.success_code in ('1000','000000')):return False
        with self.connect() as db,db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT * FROM incidents WHERE owner=? AND vehicle=? AND (interface_recovered_at IS NULL OR fresh_state_outcome='waiting') ORDER BY opened_at DESC LIMIT 1",(owner,vehicle)).fetchall()
            for row in rows:
                if row['interface_recovered_at'] is None:
                    db.execute('UPDATE incidents SET interface_recovered_at=? WHERE id=?',(now,row['id']))
                    db.execute('INSERT INTO probes VALUES(?,?,?,?)',(row['id'],now,scope,'status_success'))
                if (type(vehicle_state) is int and -30000<=now-vehicle_state<=180000
                        and (row['baseline'] is None or vehicle_state>row['baseline'])):
                    db.execute("UPDATE incidents SET fresh_state_seen_at=?,fresh_vehicle_state_at=?,fresh_state_outcome='seen' WHERE id=?",(now,vehicle_state,row['id']))
            return True
