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
from .monitor import Monitor
from .profiles import vehicle_profile
from .notifications import WeComSender
from .storage import DEFAULT_PATH, load, save


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


def read_status(root):
    root = Path(root)
    health = load(root / 'monitor-health.json')
    if not health:
        return {'status': 'not_started', 'events': []}
    heartbeat = float(health.get('heartbeat', '0'))
    allowed = max(180000, float(health.get('next_check', '0')) - heartbeat + 60000)
    result = dict(health, online=health.get('status') != 'stopped' and 0 <= time.time() * 1000 - heartbeat <= allowed, events=[])
    path = root / 'tracks.sqlite3'
    if path.exists():
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            rows = db.execute('SELECT kind,summary,delivery,error,created FROM monitor_events ORDER BY created DESC,rowid DESC LIMIT 10').fetchall()
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
        self.monitor = Monitor(self.root / 'tracks.sqlite3', active_codes, stopped_codes)
        self.sender = sender if sender is not None else WeComSender(self.root / 'wecom-webhook.json')
        self.blocked_fingerprint = None
        self.failures = 0

    def health(self):
        return load(self.root / 'monitor-health.json')

    def tick(self, now=None):
        live_clock = now is None
        now = int(time.time() * 1000) if now is None else now
        health = self.health()
        health.update(heartbeat=str(now))
        delay = 60
        fingerprint = None
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
                profile = vehicle_profile(binding, choices.index(vin) + 1, len(choices))
                health['status'] = self.monitor.observe(binding, raw, observed,
                    battery_capacity_kwh=profile.get('battery_capacity_kwh'))
                state = self.monitor.status(binding)
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
        health['next_check'] = str(now + delay * 1000)
        save(self.root / 'monitor-health.json', health)
        return delay


def run(session_path=DEFAULT_PATH, vehicle=None, once=False, active_codes=(), stopped_codes=()):
    root = Path(session_path).parent
    stop = threading.Event()
    with process_lock(root / 'monitor.lock'):
        runner = Runner(session_path, vehicle, active_codes=active_codes, stopped_codes=stopped_codes)
        previous = {}
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, lambda *_: stop.set())
            print('自动监控已启动：60 秒轮询；行程下电等待 10 分钟；充电起止通知。', flush=True)
            while not stop.is_set():
                delay = runner.tick()
                if once:
                    break
                stop.wait(delay)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            health = runner.health()
            health.update(status='stopped', heartbeat=str(int(time.time() * 1000)))
            save(root / 'monitor-health.json', health)
    return 0
