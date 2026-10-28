"""Odometer evidence across unobserved driving, separate from trip counts."""
import hashlib
import json
import sqlite3
from pathlib import Path
from .private_state import database
from .usage_events import number
from .start_evidence import MAX_GAP


class MileageGaps:
    def __init__(self,path):self.path=Path(path)

    def record(self,vehicle,before,after,active=False):
        if active or not before or any(p.get('off') is not True or p.get('charging') is not False for p in (before,after)):
            return False
        left,right=(number(p.get('time'),1,32503680000000) for p in (before,after))
        a,b=(number(p.get('km'),0,1e7) for p in (before,after))
        seen=number(after.get('observed'),1,32503680000000)
        if (None in (left,right,a,b,seen) or right-left<=MAX_GAP
                or not -30000<=seen-right<=MAX_GAP or b<=a):return False
        identity=hashlib.sha256(json.dumps([vehicle,left,right,a,b]).encode()).hexdigest()
        with database(self.path) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS mileage_gaps ('
                'id TEXT PRIMARY KEY,vehicle TEXT,left_time INTEGER,right_time INTEGER,observed_at INTEGER,'
                'odometer_before REAL,odometer_after REAL,distance_km REAL,soc_before REAL,soc_after REAL)')
            return bool(db.execute('INSERT OR IGNORE INTO mileage_gaps VALUES(?,?,?,?,?,?,?,?,?,?)',
                (identity,vehicle,left,right,seen,a,b,round(b-a,3),number(before.get('soc'),0,100),
                 number(after.get('soc'),0,100))).rowcount)

    def between(self,vehicle,lower,upper,now):
        if not self.path.exists():return []
        with sqlite3.connect(self.path.absolute().as_uri()+'?mode=ro',uri=True,timeout=5) as db:
            db.row_factory=sqlite3.Row
            rows=db.execute('SELECT id,left_time,right_time,observed_at,odometer_before,odometer_after,'
                'distance_km,soc_before,soc_after FROM mileage_gaps WHERE vehicle=? AND right_time>=? '
                'AND right_time<? AND right_time<=? AND observed_at<=? ORDER BY right_time,id',
                (vehicle,lower,upper,now,now)).fetchall()
            return [dict(row,basis='odometer_gap',date_basis='recovery_observation',status='pending') for row in rows]
