"""Private latest-vehicle snapshots shared by monitor and Web processes."""
from contextlib import closing
import hashlib
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sqlite3
from .snapshot_archive import SnapshotArchive, validate_timestamp
from .archive_reader import _private, MAX_PAYLOAD_BYTES
from .sqlite_files import prepare_database_file


class SnapshotUnavailable(OSError):
    """The local latest-state projection cannot safely be decoded."""


def _validate_times(*values):
    try:
        for value in values:validate_timestamp(value)
    except ValueError:
        raise SnapshotUnavailable('本地车辆快照时间无效。') from None


def _validate_metadata(state_time,fetched_at,observed_at,revision):
    _validate_times(fetched_at,observed_at)
    if state_time is not None:_validate_times(state_time)
    if type(revision) is not int or not 1<=revision<=9223372036854775807:
        raise SnapshotUnavailable('本地车辆快照版本无效。')


def _reject_constant(value):
    raise ValueError('non-finite snapshot value')


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('non-finite snapshot value')
    return number


def _time(raw):
    value = raw.get('updateTime') if isinstance(raw, dict) else None
    if type(value) in (int, float) and 0 <= value <= 9999999999999:
        return int(value)
    if isinstance(value, str) and len(value) <= 13 and value.isdecimal():
        return int(value)
    return None


class SnapshotStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _private(self.path.parent,directory=True)
        prepare_database_file(self.path)
        _private(self.path)
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('''CREATE TABLE IF NOT EXISTS snapshots (
            scope_key TEXT NOT NULL, vehicle_key TEXT NOT NULL, state_time INTEGER,
            fetched_at INTEGER NOT NULL, observed_at INTEGER NOT NULL,
            revision INTEGER NOT NULL, digest TEXT NOT NULL, raw TEXT NOT NULL,
            PRIMARY KEY(scope_key, vehicle_key))''')
        db.execute('''CREATE TABLE IF NOT EXISTS snapshot_publications (
            scope_key TEXT NOT NULL, vehicle_key TEXT NOT NULL,
            fetched_at INTEGER NOT NULL, observed_at INTEGER NOT NULL,
            PRIMARY KEY(scope_key, vehicle_key))''')
        db.commit()
        return db

    def bind_archive(self, scope_key, vehicle_key, owner_key):
        """Associate a verified account/vehicle with a session, without rewriting reads."""
        if not all(isinstance(v,str) and 0<len(v)<=256 for v in (scope_key,vehicle_key,owner_key)):
            raise ValueError('归档账户关联无效。')
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS archive_accounts (scope_key TEXT NOT NULL,vehicle_key TEXT NOT NULL,owner_key TEXT NOT NULL,PRIMARY KEY(scope_key,vehicle_key))')
            db.execute('CREATE INDEX IF NOT EXISTS archive_accounts_owner ON archive_accounts(owner_key,vehicle_key,scope_key)')
            db.execute('INSERT OR IGNORE INTO archive_accounts VALUES (?,?,?)',(scope_key,vehicle_key,owner_key))
            if db.execute('SELECT owner_key FROM archive_accounts WHERE scope_key=? AND vehicle_key=?',(scope_key,vehicle_key)).fetchone()[0]!=owner_key:
                raise ValueError('归档会话已属于其他账户，不能重新归属。')

    def publish(self, scope_key, vehicle_key, raw, observed_at, fetched_at=None, source='unknown', owner_key=None):
        if not all(isinstance(value, str) and value for value in (scope_key, vehicle_key)):
            raise ValueError('快照作用域或车辆无效。')
        if not isinstance(raw, dict) or type(observed_at) is not int:
            raise ValueError('车辆快照格式无效。')
        fetched_at = observed_at if fetched_at is None else fetched_at
        if type(fetched_at) is not int:
            raise ValueError('车辆读取时间无效。')
        validate_timestamp(observed_at)
        validate_timestamp(fetched_at)
        encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        state_time = _time(raw)
        change = 'new' if state_time is not None else 'time_unknown'
        # Archive first, including unchanged/older/unknown-time successful reads.
        # If the archive fails, do not advance latest state or downstream events.
        # A later latest-store failure may leave an authentic archived read;
        # retries are idempotent and never delete that evidence.
        if owner_key is not None:self.bind_archive(scope_key,vehicle_key,owner_key)
        SnapshotArchive(self.path.parent / 'snapshot-archive').append(
            scope_key, vehicle_key, encoded, state_time, observed_at, fetched_at, source)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state_time,revision,digest,fetched_at,observed_at,raw=? '
                             'FROM snapshots WHERE scope_key=? AND vehicle_key=?',
                             (encoded,scope_key, vehicle_key)).fetchone()
            if row:
                old_time, revision, old_digest, old_fetched, old_observed, payload_matches = row
                _validate_metadata(old_time,old_fetched,old_observed,revision)
                if old_time is not None and (state_time is None or state_time < old_time):
                    return {'changed': False, 'revision': revision,
                            'change': 'time_unknown' if state_time is None else 'regression'}
                if state_time == old_time:
                    watermark = db.execute('SELECT fetched_at,observed_at FROM snapshot_publications '
                                           'WHERE scope_key=? AND vehicle_key=?',(scope_key,vehicle_key)).fetchone()
                    if watermark is not None:_validate_times(*watermark)
                    if (fetched_at,observed_at) < (watermark or (old_fetched,old_observed)):
                        kind = 'superseded'
                        if digest == old_digest:
                            kind = 'repeat' if state_time is not None else 'time_unknown'
                        return {'changed':False,'revision':revision,
                                'change':kind}
            # Keep read ordering independent of content revisions: a newer
            # identical read also defeats a delayed, older conflicting payload.
            db.execute('INSERT OR REPLACE INTO snapshot_publications VALUES (?,?,?,?)',
                       (scope_key,vehicle_key,fetched_at,observed_at))
            if row:
                if state_time == old_time and digest == old_digest and payload_matches:
                    return {'changed': False, 'revision': revision,
                            'change': 'repeat' if state_time is not None else 'time_unknown'}
                if state_time is not None and state_time == old_time:
                    change = 'revision'
                if revision==9223372036854775807:
                    raise SnapshotUnavailable('本地车辆快照版本已达上限。')
                revision += 1
            else:
                revision = 1
            db.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?)',
                       (scope_key, vehicle_key, state_time, fetched_at, observed_at,
                        revision, digest, encoded))
            return {'changed': True, 'revision': revision, 'change': change}

    def read(self, scope_key, vehicle_key, known_revision=None):
        """Read a changed snapshot without loading an already-rendered payload."""
        if not scope_key or not vehicle_key:
            return None
        if not self.path.exists() and not self.path.is_symlink():
            return None
        _private(self.path.parent,directory=True)
        _private(self.path)
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            try:
                row = db.execute('''SELECT state_time,fetched_at,observed_at,revision,
                                    CASE WHEN (? IS NULL OR revision!=?)
                                         AND length(CAST(raw AS BLOB))<=? THEN raw END,digest
                                    FROM snapshots WHERE scope_key=? AND vehicle_key=?''',
                                 (known_revision,known_revision,MAX_PAYLOAD_BYTES,scope_key, vehicle_key)).fetchone()
            except sqlite3.OperationalError:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots'").fetchone():
                    return None
                raise
        if not row:
            return None
        _validate_metadata(*row[:4])
        if known_revision==row[3]:return None
        encoded = row[4]
        if not isinstance(encoded,str) or hashlib.sha256(encoded.encode()).hexdigest() != row[5]:
            raise SnapshotUnavailable('本地车辆快照内容无法校验。')
        try:
            raw = json.loads(encoded,parse_constant=_reject_constant,parse_float=_finite_float)
            if not isinstance(raw,dict):
                raise ValueError('snapshot must be an object')
        except (TypeError,ValueError,RecursionError):
            raise SnapshotUnavailable('本地车辆快照内容无法解析。') from None
        return {'state_time': row[0], 'fetched_at': row[1], 'observed_at': row[2],
                'revision': row[3], 'raw': raw}


def session_scope(session):
    """Stable private scope; digest never leaves server-side storage lookups."""
    if not isinstance(session, dict):
        raise ValueError('车辆会话无效。')
    return hashlib.sha256(json.dumps(session, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class ArchiveScopeSelection:
    scope: str
    vehicle: str
    registry: str = ''
    identity: tuple = ()
    owner: object = None
    watermark: int = 0

    def validate(self):
        from .archive_reader import _private, ArchiveChanged
        if not self.registry:return
        path=Path(self.registry)
        try:
            _private(path.parent,directory=True);_private(path)
            info=path.stat()
            if (info.st_dev,info.st_ino)!=self.identity:raise OSError()
        except OSError:
            raise ArchiveChanged('账号历史关联库已变化，请重新读取。') from None


def archive_aliases(path, scope, vehicle):
    """A fixed-size verified selector, never an enumerated/truncated scope list."""
    path=Path(path)
    if not path.exists() and not path.is_symlink():return ArchiveScopeSelection(scope,vehicle)
    from .archive_reader import _private
    _private(path.parent,directory=True);_private(path)
    info=path.stat();identity=(info.st_dev,info.st_ino)
    with closing(sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='archive_accounts'").fetchone():return ArchiveScopeSelection(scope,vehicle)
        owner=db.execute('SELECT owner_key FROM archive_accounts WHERE scope_key=? AND vehicle_key=?',(scope,vehicle)).fetchone()
        if owner is None:return ArchiveScopeSelection(scope,vehicle)
        maximum=db.execute('SELECT MAX(rowid) FROM archive_accounts WHERE owner_key=? AND vehicle_key=?',(owner[0],vehicle)).fetchone()[0]
        return ArchiveScopeSelection(scope,vehicle,str(path.absolute()),identity,owner[0],maximum)
