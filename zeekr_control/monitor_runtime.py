"""One outbound-only background monitor, independent of the dashboard process."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import threading
import time

from .client import Client
from .cli import find_vins
from .errors import ApiError, RateLimited
from .monitor import Monitor, MAX_AGE, STOP_WAIT
from .vehicle_state import decode
from .geocoding import AmapGeocoder
from .profiles import vehicle_profile
from .notifications import WeComSender
from .storage import DEFAULT_PATH, load, save
from .snapshots import SnapshotStore, session_scope


def enable_sampling(root):
    save(Path(root) / 'sampling.json', {'enabled': 'true'})


def sampling_enabled(root):
    return load(Path(root) / 'sampling.json').get('enabled', 'true') != 'false'


def collection_loop(runner, stop, once=False):
    """One owner; control changes are noticed within one second without querying."""
    deadline = 0
    previous = None
    while not stop.is_set():
        enabled = sampling_enabled(runner.root)
        if enabled != previous or time.monotonic() >= deadline:
            delay = runner.tick()
            deadline = time.monotonic() + delay
            previous = enabled
            if once:
                break
        stop.wait(1)


def background(session_path, stop):
    """Web fallback shares the monitor lock with the standalone service."""
    root = Path(session_path).parent
    while not stop.is_set():
        try:
            with process_lock(root / 'monitor.lock'):
                runner = Runner(session_path)
                try:
                    collection_loop(runner, stop)
                finally:
                    health = runner.health()
                    health.update(status='stopped', heartbeat=str(int(time.time() * 1000)))
                    save(root / 'monitor-health.json', health)
                return
        except ValueError as exc:
            if str(exc) != '监控已经运行，请勿重复启动':
                raise
        except Exception:
            # Publish no secrets; retry storage/network setup without a second owner.
            try:
                save(root / 'monitor-health.json', {'status':'blocked',
                     'heartbeat':str(int(time.time() * 1000)), 'error':'采集后台异常，请检查服务日志与存储权限。'})
            except Exception:
                pass
        stop.wait(5)


@contextmanager
def process_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.parent.stat()
    if path.parent.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('监控目录权限应为 700')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('监控锁权限应为 600')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('监控已经运行，请勿重复启动') from None
        yield
    finally:
        os.close(fd)


PUBLIC_HEALTH_FIELDS = ('status', 'heartbeat', 'next_check', 'interval', 'last_success',
                        'last_new', 'trip', 'charge')


def _safe_error(value):
    if not value:
        return ''
    text = str(value)
    for category, tokens in (
        ('认证状态异常，请检查车辆连接。', ('登录', '认证', '401', '403', 'token')),
        ('接口暂不可用，后台将按策略处理。', ('网络', 'TLS', 'HTTP 5', '限流', '冷却')),
        ('采集后台异常，请检查服务状态。', ())):
        if not tokens or any(token.lower() in text.lower() for token in tokens):
            return category


def read_status(root, vehicle=None, public=False):
    root = Path(root)
    health = load(root / 'monitor-health.json')
    if not health:
        return {'status': 'not_started', 'events': []}
    heartbeat = float(health.get('heartbeat', '0'))
    allowed = max(180000, float(health.get('next_check', '0')) - heartbeat + 60000)
    source = ({key: health[key] for key in PUBLIC_HEALTH_FIELDS if key in health}
              if public else dict(health))
    if public:
        source['error'] = _safe_error(health.get('error'))
    result = dict(source, online=health.get('status') != 'stopped' and 0 <= time.time() * 1000 - heartbeat <= allowed, events=[])
    path = root / 'tracks.sqlite3'
    if path.exists():
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            if public and not vehicle:
                rows = []
            elif public:
                rows = db.execute('SELECT kind,delivery,error,created FROM monitor_events WHERE vehicle=? ORDER BY created DESC,rowid DESC LIMIT 10', (vehicle,)).fetchall()
            else:
                rows = db.execute('SELECT kind,summary,delivery,error,created FROM monitor_events ORDER BY created DESC,rowid DESC LIMIT 10').fetchall()
            if public:
                result['events'] = [dict(kind=r[0], delivery=r[1], error=_safe_error(r[2]), created=r[3]) for r in rows]
            else:
                result['events'] = [dict(kind=r[0], summary=json.loads(r[1]), delivery=r[2], error=r[3], created=r[4]) for r in rows]
        finally:
            db.close()
    return result


class Runner:
    def __init__(self, session_path=DEFAULT_PATH, vehicle=None, client_factory=Client, sender=None,
                 active_codes=(), stopped_codes=()):
        self.session_path = Path(session_path)
        self.root = self.session_path.parent
        if vehicle is not None and (type(vehicle) is not int or vehicle < 1):
            raise ValueError('车辆序号必须为正整数')
        if set(active_codes) & set(stopped_codes):
            raise ValueError('充电与停止状态码不可重叠')
        self.vehicle = vehicle
        self.client_factory = client_factory
        self.monitor = Monitor(self.root / 'tracks.sqlite3', active_codes, stopped_codes,
                               address_resolver=AmapGeocoder(self.root / 'amap-geocoding.json'))
        self.sender = sender if sender is not None else WeComSender(self.root / 'wecom-webhook.json')
        self.blocked_fingerprint = None
        self.failures = 0
        self.parked_since = None
        self.parked_last = None
        self.sampling_interval = 60

    def health(self):
        return load(self.root / 'monitor-health.json')

    def interval_for(self, raw, now, state):
        point = decode(raw, self.monitor.active_codes, self.monitor.stopped_codes)
        previous = self.parked_last
        parked = (point['off'] is True and point['speed'] == 0
                  and point['charging'] is False and (not state['trip'] or state['trip']['stop'])
                  and not state['charge'])
        if previous and (point['km'] is None or previous['km'] is None or point['km'] != previous['km']):
            parked = False
        fresh = point['time'] is not None and -30000 <= now - point['time'] <= MAX_AGE
        if not parked or not fresh:
            # Stale cache never starts a parking timer, but an already confirmed
            # parked car can stay slow until a new observation contradicts it.
            if parked and self.sampling_interval == 300:
                return 300
            self.parked_since = self.parked_last = None
            self.sampling_interval = 60
            return 60
        if previous and point['time'] <= previous['time']:
            return self.sampling_interval
        continuous = previous and 0 <= now - previous['observed'] <= MAX_AGE and point['time'] - previous['time'] <= MAX_AGE
        if self.parked_since is None or (not continuous and self.sampling_interval != 300):
            self.parked_since = (now, point['time'])
        self.parked_last = dict(point, observed=now)
        if not state['trip'] and now - self.parked_since[0] >= STOP_WAIT and point['time'] - self.parked_since[1] >= STOP_WAIT:
            self.sampling_interval = 300
        return self.sampling_interval

    def tick(self, now=None):
        live_clock = now is None
        now = int(time.time() * 1000) if now is None else now
        health = self.health()
        health.update(heartbeat=str(now))
        delay = 60
        fingerprint = None
        if not sampling_enabled(self.root):
            self.parked_since = self.parked_last = None
            self.sampling_interval = 60
            health.update(status='paused', error='', interval='60', next_check=str(now + 60000))
            save(self.root / 'monitor-health.json', health)
            return 60
        try:
            session = load(self.session_path)
            fingerprint = hashlib.sha256(json.dumps(session, sort_keys=True).encode()).hexdigest()
            if self.blocked_fingerprint == fingerprint:
                health['status'] = 'blocked'
            else:
                if not session.get('accessToken'):
                    raise ApiError('尚未登录，请更新车辆会话后恢复监控')
                client = self.client_factory(session)
                vehicles = client.vehicles()
                binding = load(self.root / 'monitor-binding.json').get('vehicle_key')
                choices = []
                for entry in vehicles:
                    vins = find_vins(entry)
                    choices.append(next(iter(vins)) if len(vins) == 1 else None)
                if binding:
                    matches = [v for v in choices if v and hashlib.sha256(v.encode()).hexdigest() == binding]
                    if len(matches) != 1:
                        raise ApiError('原绑定车辆不在当前车辆列表中；请核对账号和车辆')
                    vin = matches[0]
                else:
                    if self.vehicle is None and len(choices) != 1:
                        raise ApiError('多辆车或无车辆，请用 --vehicle 明确选择')
                    index = self.vehicle or 1
                    if index > len(choices) or not choices[index - 1]:
                        raise ApiError('车辆序号无效或未返回唯一 VIN')
                    vin = choices[index - 1]
                    binding = hashlib.sha256(vin.encode()).hexdigest()
                    save(self.root / 'monitor-binding.json', {'vehicle_key': binding})
                raw = client.status(vin)
                # Production captures observation time after the potentially slow request.
                observed = int(time.time() * 1000) if live_clock else now
                fetched = getattr(client, 'last_query_fetched_at', None)
                fetched_at = int(fetched * 1000) if type(fetched) in (int, float) else observed
                SnapshotStore(self.root / 'snapshots.sqlite3').publish(
                    session_scope(session), binding, raw, observed, fetched_at=fetched_at)
                profile = vehicle_profile(binding, choices.index(vin) + 1, len(choices))
                health['status'] = self.monitor.observe(binding, raw, observed,
                    battery_capacity_kwh=profile.get('battery_capacity_kwh'), profile=profile)
                state = self.monitor.status(binding)
                delay = self.interval_for(raw, observed, state)
                if health['status'] == 'fresh':
                    if self.monitor.tracks.record(binding, raw, observed, 180):
                        health['last_new'] = str(observed)
                with self.monitor.tracks.connect() as db:
                    newest = db.execute('SELECT MAX(observed_time) FROM observations WHERE vehicle=?', (binding,)).fetchone()[0]
                if newest is not None:
                    health['last_new'] = str(newest)
                health['interval'] = str(delay)
                health.update(error='', last_success=str(observed),
                              trip='waiting' if state['trip'] and state['trip']['stop'] else 'driving' if state['trip'] else 'idle',
                              charge='charging' if state['charge'] else 'idle' if state['last'] and state['last']['charging'] is False else 'unknown',
                              signals=json.dumps(state['last']['signals'], ensure_ascii=False) if state['last'] else '{}')
                self.failures = 0
        except RateLimited as exc:
            delay = max(60, exc.seconds)
            health.update(status='cooldown', error='接口限流，等待冷却')
        except ApiError as exc:
            error = str(exc)
            if any(token in error for token in ('网络或 TLS', 'HTTP 5', '并发锁')):
                self.failures += 1
                delay = min(900, 60 * 2 ** min(self.failures, 4))
                health.update(status='retrying', error=error[:150])
            else:
                self.blocked_fingerprint = fingerprint
                health.update(status='blocked', error=error[:150])
        # Storage errors escape and stop the worker, never inventing transitions.
        self.monitor.deliver(self.sender, now)
        health['next_check'] = str((int(time.time() * 1000) if live_clock else now) + delay * 1000)
        save(self.root / 'monitor-health.json', health)
        return delay


def run(session_path=DEFAULT_PATH, vehicle=None, once=False, active_codes=(), stopped_codes=()):
    root = Path(session_path).parent
    stop = threading.Event()
    previous = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda *_: stop.set())
        enable_sampling(root)
        while not stop.is_set():
            try:
                with process_lock(root / 'monitor.lock'):
                    runner = Runner(session_path, vehicle, active_codes=active_codes, stopped_codes=stopped_codes)
                    try:
                        print('统一采集已启动：默认 60 秒；确认停车后 300 秒；充电起止通知。', flush=True)
                        collection_loop(runner, stop, once)
                    finally:
                        health = runner.health()
                        health.update(status='stopped', heartbeat=str(int(time.time() * 1000)))
                        save(root / 'monitor-health.json', health)
                    break
            except ValueError as exc:
                if str(exc) != '监控已经运行，请勿重复启动' or once:
                    raise
                # Web may already own collection. Stay available to take over
                # after it exits instead of fighting it through service restarts.
                stop.wait(5)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0
