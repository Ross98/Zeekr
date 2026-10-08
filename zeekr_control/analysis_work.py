"""Disposable private work tables for exact, bounded-memory analytics.

Only projected observation metadata, decoded scalar state and location are kept;
never vehicle response bodies, credentials, or a persistent analysis cache.
"""
import json
from pathlib import Path
import sqlite3
import tempfile


MAX_RESULT_BYTES = 4 * 1024 * 1024


class AnalysisCapacity(ValueError):
    """The disposable analysis work file reached its explicit size budget."""


class ResultRows(list):
    """Stop fragmented output before an unbounded Python result can accumulate."""
    def __init__(self):
        super().__init__()
        self.encoded_bytes = 2

    def append(self, row):
        size = len(json.dumps(row, ensure_ascii=False, separators=(',', ':')).encode())+1
        if self.encoded_bytes+size > MAX_RESULT_BYTES:
            raise AnalysisCapacity('分析结果片段过多，请缩小日期范围后重试。')
        self.encoded_bytes += size
        super().append(row)


class WorkDatabase:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='zeekr-analysis-')
        self.path = Path(self.temporary.name) / 'work.sqlite3'
        self.db = None

    def __enter__(self):
        try:
            self.path.touch(mode=0o600)
            self.db = sqlite3.connect(self.path)
            self.db.execute('PRAGMA page_size=4096')
            self.db.execute('PRAGMA journal_mode=OFF')
            self.db.execute('PRAGMA synchronous=OFF')
            self.db.execute('PRAGMA cache_size=-1024')
            self.db.execute('PRAGMA mmap_size=0')
            self.db.execute('PRAGMA temp_store=FILE')
            self.db.execute('PRAGMA max_page_count=65536')  # 256 MiB, below service LimitFSIZE.
            return self
        except Exception as error:
            self.__exit__(type(error), error, error.__traceback__)
            raise

    def __exit__(self, kind, error, traceback):
        try:
            if self.db is not None:
                self.db.close()
        finally:
            self.temporary.cleanup()
        if isinstance(error, sqlite3.DatabaseError) and 'full' in str(error).lower():
            raise AnalysisCapacity('分析临时空间达到上限，请缩小范围或稍后重试。') from error


class TimeMap(WorkDatabase):
    """Timestamp-to-day values; revisions replace values without a Python-size set."""
    def __enter__(self):
        super().__enter__()
        try:
            self.db.execute('CREATE TABLE times (stamp PRIMARY KEY, day TEXT, parked INTEGER)')
            return self
        except Exception as error:
            self.__exit__(type(error), error, error.__traceback__)
            raise

    def set(self, stamp, day=None, parked=False):
        self.db.execute('INSERT OR REPLACE INTO times VALUES (?,?,?)', (stamp, day, int(parked)))

    def add(self, stamp):
        return self.db.execute('INSERT OR IGNORE INTO times(stamp) VALUES (?)', (stamp,)).rowcount == 1

    def daily(self):
        return self.db.execute('SELECT day,COUNT(*),SUM(parked),MIN(CASE WHEN parked THEN stamp END),'
                               'MAX(CASE WHEN parked THEN stamp END) FROM times GROUP BY day')


class SampleRows:
    def __init__(self, store, canonical=False, where='1', args=()):
        self.store, self.canonical, self.where, self.args = store, canonical, where, tuple(args)

    def query(self, columns='r.*', suffix=''):
        source = 'canonical c JOIN samples r ON r.id=c.source_id' if self.canonical else 'samples r'
        order = 'c.id' if self.canonical else 'r.observed,r.id'
        return self.store.db.execute('SELECT '+columns+' FROM '+source+' WHERE '+self.where+
                                     ' ORDER BY '+order+' '+suffix, self.args)

    def indexed(self):
        columns = 'c.id,r.*' if self.canonical else 'r.id,r.*'
        for row in self.query(columns):
            yield row[0], self.store.decode(row[1:])

    def __iter__(self):
        for row in self.query():
            yield self.store.decode(row)

    def projected(self, indexed=False):
        """Run calculations need scalar timing, not the full public metadata."""
        columns=('c.id' if self.canonical else 'r.id')+',r.observed,r.stamp,r.fresh,r.soc,r.charging,r.km,r.off,r.speed,r.gear,r.location,r.change'
        for row in self.query(columns):
            sample=dict(record=dict(observed_at=row[1],state_time=row[2],flags=[] if row[3] else ['invalid'],change=row[11]),
                        state=dict(soc=row[4],charging=None if row[5] is None else bool(row[5]),km=row[6],
                                   off=None if row[7] is None else bool(row[7]),speed=row[8],gear=row[9]),
                        location=json.loads(row[10]))
            yield (row[0],sample) if indexed else sample

    def with_condition(self, where, args=()):
        return SampleRows(self.store,self.canonical,'('+self.where+') AND ('+where+')',self.args+tuple(args))

    def first(self):
        row = self.query(suffix='LIMIT 1').fetchone()
        return self.store.decode(row) if row else None

    def between_ids(self, first, last):
        return SampleRows(self.store, self.canonical, self.where+' AND c.id BETWEEN ? AND ?',
                          self.args+(first, last))


class SampleStore(WorkDatabase):
    """Replayable scalar projection, ordered and canonicalized using v6 rules."""
    def __init__(self, samples):
        super().__init__()
        self.samples = samples

    def __enter__(self):
        super().__enter__()
        try:
            from .parking_events import fresh, observation_time
            self.db.execute('CREATE TABLE samples (id INTEGER PRIMARY KEY, observed, stamp, instant, fresh INTEGER,'
                            'record TEXT, soc, charging INTEGER, km, off INTEGER, speed, gear TEXT,'
                            'location TEXT, inside_temp, inside_time, change TEXT, flagged INTEGER)')
            def encoded():
                for sample in self.samples:
                    record, state = sample['record'], sample['state']
                    projection = (json.dumps(record, ensure_ascii=False, separators=(',', ':')),
                                  json.dumps(sample.get('location'), ensure_ascii=False, separators=(',', ':')))
                    if any(len(part.encode()) > 8192 for part in projection):
                        raise AnalysisCapacity('分析观测元数据过大，无法安全读取。')
                    yield (record['observed_at'], record.get('state_time'), observation_time(sample),
                           int(fresh(sample)), projection[0], state.get('soc'), state.get('charging'),
                           state.get('km'), state.get('off'), state.get('speed'), state.get('gear'),
                           projection[1], sample.get('inside_temp'), sample.get('inside_time'),
                           record.get('change'),int(bool(record.get('flags'))))
            self.db.executemany('INSERT INTO samples VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', encoded())
            self.db.execute('CREATE INDEX samples_observed ON samples(observed,id)')
            self.db.execute('CREATE INDEX samples_instant ON samples(instant,id)')
            self.db.execute('CREATE TABLE canonical (id INTEGER PRIMARY KEY, source_id INTEGER UNIQUE)')
            previous, identity = None, 0
            for source_id,stamp,flagged,change in self.raw().query('r.id,r.stamp,r.flagged,r.change'):
                advances=(previous is not None and type(stamp) in (int,float) and type(previous) in (int,float) and stamp>previous)
                if change == 'repeat' and not advances:
                    continue
                if change == 'revision' and not flagged and identity and stamp == previous:
                    self.db.execute('UPDATE canonical SET source_id=? WHERE id=?', (source_id, identity))
                else:
                    identity += 1
                    self.db.execute('INSERT INTO canonical VALUES (?,?)', (identity, source_id))
                previous = stamp
            self.samples = None
            return self
        except Exception as error:
            self.__exit__(type(error), error, error.__traceback__)
            raise

    @staticmethod
    def decode(row):
        state = dict(soc=row[6], charging=None if row[7] is None else bool(row[7]), km=row[8],
                     off=None if row[9] is None else bool(row[9]), speed=row[10], gear=row[11])
        return dict(record=json.loads(row[5]), state=state, location=json.loads(row[12]),
                    inside_temp=row[13], inside_time=row[14])

    def raw(self, where='1', args=()):
        return SampleRows(self, False, where, args)

    def canonical(self, where='1', args=()):
        return SampleRows(self, True, where, args)
