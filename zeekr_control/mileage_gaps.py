"""Odometer evidence across unobserved driving, separate from trip counts."""
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from .private_state import database
from .usage_events import number, MAX_SUMMARY_BYTES, MAX_SCAN
from .start_evidence import MAX_GAP
from .errors import RecordConflict
from .archive_reader import _private


class MileageGaps:
    def __init__(self,path,tracks=None):
        self.path=Path(path)
        self.tracks=Path(tracks) if tracks else self.path.parent/'tracks.sqlite3'

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
        return self._rows(None,vehicle,lower,upper,now,False)

    def history(self,owner,vehicle,lower,upper,now):
        return self._rows(owner,vehicle,lower,upper,now,True)

    def _rows(self,owner,vehicle,lower,upper,now,completed):
        if not self.path.exists():return []
        _private(self.path.parent,directory=True);_private(self.path)
        with closing(sqlite3.connect(self.path.absolute().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            db.row_factory=sqlite3.Row
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='gap_completions'").fetchone()
            extra=',c.owner,c.body,c.revision,c.event_id' if exists else ',NULL AS owner,NULL AS body,0 AS revision,NULL AS event_id'
            join=' LEFT JOIN gap_completions c ON c.gap_id=g.id' if exists else ''
            pending=' AND c.gap_id IS NULL' if exists and not completed else ''
            rows=db.execute('SELECT g.id,left_time,right_time,observed_at,odometer_before,odometer_after,'
                'distance_km,soc_before,soc_after'+extra+' FROM mileage_gaps g'+join+' WHERE vehicle=? AND right_time>=? '
                'AND right_time<? AND right_time<=? AND observed_at<=?'+pending+' ORDER BY right_time,g.id',
                (vehicle,lower,upper,now,now)).fetchall()
            result=[]
            for row in rows:
                item={k:row[k] for k in row.keys() if k not in ('owner','body','revision','event_id')}
                item.update(basis='odometer_gap',date_basis='recovery_observation',status='completed' if row['event_id'] else 'pending')
                if completed:
                    item.update(revision=row['revision'],event_id=row['event_id'],can_edit=not row['owner'] or row['owner']==owner)
                    if row['body'] and row['owner']==owner:item['completion']=json.loads(row['body'])
                result.append(item)
            return result

    def completion(self,owner,vehicle,event_id):
        if not self.path.exists():return None
        with closing(sqlite3.connect(self.path.absolute().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='gap_completions'").fetchone():return None
            row=db.execute('SELECT g.*,c.body,c.revision FROM gap_completions c JOIN mileage_gaps g ON g.id=c.gap_id '
                           'WHERE c.owner=? AND g.vehicle=? AND c.event_id=?',(owner,vehicle,event_id)).fetchone()
            return dict(json.loads(row['body']),revision=row['revision'],gap_id=row['id'],
                        evidence={k:row[k] for k in ('left_time','right_time','odometer_before','odometer_after','distance_km','soc_before','soc_after')}) if row else None

    def update(self,owner,vehicle,data,guard=None,now=None):
        """Attach both private databases: the trip and status commit together."""
        now=int(time.time()*1000) if now is None else now
        identity=data.get('gap_id');revision=data.get('revision')
        if (not isinstance(identity,str) or len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity)
                or type(revision) is not int or revision<0 or not owner):raise ValueError('补全记录或版本无效。')
        if 'distance_km' in data:raise ValueError('里程来自原始证据，不能改写。')
        try:
            start,end=[int(datetime.strptime(data[key],'%Y-%m-%dT%H:%M').replace(tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()*1000) for key in ('start','end')]
        except (KeyError,ValueError,TypeError,OverflowError):raise ValueError('请填写有效的北京时间。') from None
        labels=[]
        for key in ('start_place','end_place'):
            text=data.get(key)
            if not isinstance(text,str) or not 1<=len(text.strip())<=80 or any(ord(c)<32 for c in text):raise ValueError('地点需为 1–80 字的单行文字。')
            labels.append(text.strip())
        if not self.path.exists() or not self.tracks.is_file():raise ValueError('原始证据不可用，请重新读取。')
        _private(self.tracks.parent,directory=True);_private(self.tracks)
        if guard:guard()
        event_id='manual_'+identity
        with database(self.path) as db:
            db.execute('ATTACH DATABASE ? AS records',(str(self.tracks.resolve()),))
            if db.execute('PRAGMA main.journal_mode').fetchone()[0]!='delete' or db.execute('PRAGMA records.journal_mode').fetchone()[0]!='delete':
                raise ValueError('当前存储状态无法安全补全，请检查服务。')
            db.execute('PRAGMA records.synchronous=FULL')
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS gap_completions (gap_id TEXT PRIMARY KEY,owner TEXT NOT NULL,event_id TEXT UNIQUE NOT NULL,revision INTEGER NOT NULL,body TEXT NOT NULL,created INTEGER NOT NULL,updated INTEGER NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS gap_completion_history (gap_id TEXT,revision INTEGER,owner TEXT,body TEXT,updated INTEGER,PRIMARY KEY(gap_id,revision))')
                gap=db.execute('SELECT * FROM mileage_gaps WHERE id=? AND vehicle=?',(identity,vehicle)).fetchone()
                if not gap:raise ValueError('记录不属于当前车辆，或原始证据不可用。')
                old=db.execute('SELECT * FROM gap_completions WHERE gap_id=?',(identity,)).fetchone()
                if old and old['owner']!=owner:raise ValueError('当前账号不能修改这条补全记录。')
                if (old['revision'] if old else 0)!=revision:raise RecordConflict('记录已补全或修改，请重新读取后再核对。')
                if gap['observed_at']>now or gap['right_time']>now:raise ValueError('原始观测晚于当前时间，请重新读取。')
                if number(gap['distance_km'],.001,1e7) is None or round(gap['odometer_after']-gap['odometer_before'],3)!=gap['distance_km']:
                    raise ValueError('原始里程证据不一致，不能补全。')
                if not gap['left_time']<=start<end<=min(gap['right_time'],now) or end-start>366*86400000:
                    raise ValueError('出发须早于到达，且两者须在原始观测范围内、不能晚于当前时间。')
                duplicate=db.execute('SELECT 1 FROM gap_completions c JOIN mileage_gaps g ON g.id=c.gap_id WHERE g.vehicle=? AND g.id!=? AND g.odometer_before<? AND g.odometer_after>?',
                                     (vehicle,identity,gap['odometer_after'],gap['odometer_before'])).fetchone()
                if duplicate:raise RecordConflict('这段里程已在其他补全记录中使用，不能重复计入。')
                has_trash=db.execute("SELECT 1 FROM records.sqlite_master WHERE name='trip_record_trash'").fetchone()
                visible=' AND NOT EXISTS (SELECT 1 FROM records.trip_record_trash t WHERE t.vehicle=e.vehicle AND t.event_id=e.id)' if has_trash else ''
                if has_trash and db.execute('SELECT 1 FROM records.trip_record_trash WHERE vehicle=? AND event_id=?',(vehicle,event_id)).fetchone():
                    raise ValueError('这条行程已移到回收站，请先恢复。')
                rows=db.execute("SELECT CASE WHEN length(CAST(summary AS BLOB))<=? THEN summary END AS summary FROM records.monitor_events e WHERE vehicle=? AND kind='trip_end' AND id!=?"+visible+' LIMIT ?',
                                (MAX_SUMMARY_BYTES,vehicle,event_id,MAX_SCAN+1))
                for index,row in enumerate(rows):
                    if index>=MAX_SCAN:raise ValueError('行程记录过多，暂无法核对重叠。')
                    try:other=json.loads(row['summary'])
                    except (ValueError,TypeError,RecursionError):raise ValueError('存在无法校验的行程，请先核对记录。') from None
                    if not isinstance(other,dict):raise ValueError('存在无法校验的行程，请先核对记录。')
                    a,b=number(other.get('start_time'),1,32503680000000),number(other.get('end_time'),1,32503680000000)
                    if b is not None and b>start and (a is None or a<end):raise RecordConflict('时间与已有行程重叠，请先核对，避免重复计数。')
                body=dict(start_time=start,end_time=end,start_place=labels[0],end_place=labels[1])
                summary=dict(start_time=start,end_time=end,duration_seconds=(end-start)/1000,distance_km=gap['distance_km'],
                             start_soc=None,end_soc=None,soc_delta=None,partial=True,
                             manual_completion=dict(source='mileage_gap',gap_id=identity,revision=revision+1))
                if old:
                    current=db.execute('SELECT summary FROM records.monitor_events WHERE id=? AND vehicle=?',(event_id,vehicle)).fetchone()
                    if not current or json.loads(current['summary']).get('manual_completion',{}).get('gap_id')!=identity:
                        raise RecordConflict('补全行程已变化，请重新读取。')
                    if not db.execute('UPDATE records.monitor_events SET summary=? WHERE id=? AND vehicle=?',(json.dumps(summary,ensure_ascii=False),event_id,vehicle)).rowcount:
                        raise RecordConflict('补全行程已变化，请重新读取。')
                else:
                    db.execute("INSERT INTO records.monitor_events(id,vehicle,kind,summary,message,created,delivery) VALUES(?,?,'trip_end',?,'',?,'cancelled')",
                               (event_id,vehicle,json.dumps(summary,ensure_ascii=False),now))
                db.execute('INSERT OR REPLACE INTO gap_completions VALUES(?,?,?,?,?,?,?)',
                           (identity,owner,event_id,revision+1,json.dumps(body,ensure_ascii=False),old['created'] if old else now,now))
                db.execute('INSERT INTO gap_completion_history VALUES(?,?,?,?,?)',(identity,revision+1,owner,json.dumps(body,ensure_ascii=False),now))
                db.execute('CREATE TABLE IF NOT EXISTS records.trip_record_revisions (vehicle TEXT PRIMARY KEY,revision INTEGER NOT NULL)')
                db.execute('INSERT INTO records.trip_record_revisions VALUES(?,1) ON CONFLICT(vehicle) DO UPDATE SET revision=revision+1',(vehicle,))
                if guard:guard()
        return dict(event_id=event_id,revision=revision+1,date=datetime.fromtimestamp(end/1000,ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d'),status='completed')
