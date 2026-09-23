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
from .geocoding import AmapGeocoder
from .trip_map import AmapStaticMap
from .profiles import vehicle_profile
from .notifications import BarkSender, DeliveryError, FallbackSender, WeComSender, compact_bark_times
from .storage import DEFAULT_PATH, load, save
from .snapshots import SnapshotStore, session_scope
from .storage_health import StorageHealth
from .personal_store import PersonalStore, account_scope
from .custom_reminders import Reminders
from .sampling import read_settings, save_settings
from .query_policy import QueryPolicy
from .archive_reader import ArchiveReader
from .automatic_insights import Analyzer, InsightCache, InsightWorker


def enable_sampling(root):
    save_settings(root, True)


def sampling_enabled(root):
    return read_settings(root)[0]


def collection_loop(runner, stop, once=False):
    """One owner; control changes are noticed within one second without querying."""
    deadline = 0
    previous = None
    previous_interval = None
    finished_at, delay = 0, None
    normal_wait = False
    while not stop.is_set():
        storage_health = getattr(runner, 'storage_health', None)
        if storage_health is not None:
            try:
                storage_health.tick()
            except Exception:
                # Health failure is visible in journal + stale Web timestamp,
                # but does not silently disable unrelated vehicle collection.
                print('存储健康巡检或预警状态持久化失败，请检查存储。', flush=True)
        enabled, interval = read_settings(runner.root)
        if interval != previous_interval and normal_wait:
            # Reschedule normal collection only; a setting change cannot shorten
            # network backoff or a server cooldown.
            deadline = finished_at + interval
        previous_interval = interval
        if enabled != previous or time.monotonic() >= deadline:
            delay = runner.tick()
            runner.start_analysis()
            normal_wait = delay == interval and runner.health().get('status') not in ('cooldown', 'retrying', 'blocked')
            finished_at = time.monotonic()
            deadline = finished_at + delay
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
                    runner.insight_worker.close()
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
            has_alerts = bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_event_alerts'").fetchone())
            alert_columns = ',a.delivery,a.error' if has_alerts else ',NULL,NULL'
            alert_join = ' LEFT JOIN monitor_event_alerts a ON a.event_id=e.id' if has_alerts else ''
            if public and not vehicle:
                rows = []
            elif public:
                rows = db.execute('SELECT e.kind,e.delivery,e.error,e.created' + alert_columns +
                    ' FROM monitor_events e' + alert_join +
                    ' WHERE e.vehicle=? ORDER BY e.created DESC,e.rowid DESC LIMIT 10', (vehicle,)).fetchall()
            else:
                rows = db.execute('SELECT e.kind,e.summary,e.delivery,e.error,e.created' + alert_columns +
                    ' FROM monitor_events e' + alert_join +
                    ' ORDER BY e.created DESC,e.rowid DESC LIMIT 10').fetchall()
            if public:
                result['events'] = [dict(kind=r[0], delivery=r[1], error=_safe_error(r[2]), created=r[3],
                                         alert_delivery=r[4], alert_error=_safe_error(r[5])) for r in rows]
            else:
                result['events'] = [dict(kind=r[0], summary=json.loads(r[1]), delivery=r[2], error=r[3], created=r[4],
                                         alert_delivery=r[5], alert_error=r[6]) for r in rows]
        finally:
            db.close()
    return result


class AuthFailureAlert:
    """One Bark attempt per observed 1509 outage, durable across restarts."""

    def __init__(self, root, sender):
        self.path = Path(root) / 'auth-failure-alert.json'
        self.sender = sender

    def blocked(self, error):
        if self.sender is None or '网关代码 1509' not in error:
            return
        if load(self.path).get('state') in ('sending', 'sent', 'failed', 'uncertain'):
            return
        save(self.path, {'state': 'sending'})
        try:
            self.sender('⚠️ 极氪采集已中断',
                        '车辆接口返回 1509，无法采集新数据或生成新通知。请在服务器重新登录极氪副账号。')
        except DeliveryError as exc:
            save(self.path, {'state': 'uncertain' if exc.ambiguous else 'failed'})
        except Exception:
            save(self.path, {'state': 'uncertain'})
        else:
            save(self.path, {'state': 'sent'})

    def recovered(self):
        if load(self.path).get('state') not in (None, 'ready'):
            save(self.path, {'state': 'ready'})


class Runner:
    def __init__(self, session_path=DEFAULT_PATH, vehicle=None, client_factory=Client, sender=None,
                 active_codes=(), stopped_codes=(), alert_sender=None):
        self.session_path = Path(session_path)
        self.root = self.session_path.parent
        if vehicle is not None and (type(vehicle) is not int or vehicle < 1):
            raise ValueError('车辆序号必须为正整数')
        if set(active_codes) & set(stopped_codes):
            raise ValueError('充电与停止状态码不可重叠')
        self.vehicle = vehicle
        self.client_factory = ((lambda session: Client(session, query_policy=QueryPolicy(self.root / 'queries.sqlite3')))
                               if client_factory is Client else client_factory)
        self.monitor = Monitor(self.root / 'tracks.sqlite3', active_codes, stopped_codes,
                               address_resolver=AmapGeocoder(self.root / 'amap-geocoding.json'),
                               map_renderer=AmapStaticMap(self.root / 'amap-geocoding.json'))
        self.sender = sender if sender is not None else WeComSender(self.root / 'wecom-webhook.json')
        self.alert_sender = (alert_sender if alert_sender is not None else
                             BarkSender(self.root / 'bark.json') if sender is None else None)
        self.reminder_sender = (FallbackSender(self.alert_sender, self.sender, compact_bark_times)
                                if self.alert_sender is not None else self.sender)
        self.auth_failure_alert = AuthFailureAlert(self.root, self.alert_sender)
        self.storage_health = StorageHealth(self.root, self.sender, self.alert_sender)
        self.reminders = Reminders(PersonalStore(self.root / 'personal.sqlite3'))
        self.reminders.recover()
        self.blocked_fingerprint = None
        self.failures = 0
        self.analysis_input = None
        self.insight_worker = InsightWorker(
            Analyzer(self.root / 'tracks.sqlite3', ArchiveReader(self.root / 'snapshot-archive')),
            InsightCache(self.root / 'automatic-insights.json'))

    def start_analysis(self):
        if self.analysis_input is None:
            return False
        scope, vehicle, observed = self.analysis_input
        self.analysis_input = None
        def guard():
            return (sampling_enabled(self.root)
                    and session_scope(load(self.session_path)) == scope
                    and load(self.root / 'monitor-binding.json').get('vehicle_key') == vehicle)
        return self.insight_worker.start(scope, vehicle, observed, guard)

    def health(self):
        return load(self.root / 'monitor-health.json')

    def tick(self, now=None):
        self.analysis_input = None
        live_clock = now is None
        now = int(time.time() * 1000) if now is None else now
        health = self.health()
        health.update(heartbeat=str(now))
        enabled, interval = read_settings(self.root)
        delay = interval
        fingerprint = None
        if not enabled:
            health.update(status='paused', error='', interval=str(interval), next_check=str(now + interval * 1000))
            save(self.root / 'monitor-health.json', health)
            return interval
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
                    session_scope(session), binding, raw, observed, fetched_at=fetched_at, source='monitor')
                profile = vehicle_profile(binding, choices.index(vin) + 1, len(choices))
                health['status'] = self.monitor.observe(binding, raw, observed,
                    battery_capacity_kwh=profile.get('battery_capacity_kwh'), profile=profile)
                state = self.monitor.status(binding)
                # Parking uses the same cadence, so starting a trip stays visible.
                if health['status'] == 'fresh':
                    if self.monitor.tracks.record(binding, raw, observed, 180):
                        health['last_new'] = str(observed)
                with self.monitor.tracks.connect() as db:
                    newest = db.execute('SELECT MAX(observed_time) FROM observations WHERE vehicle=?', (binding,)).fetchone()[0]
                if newest is not None:
                    health['last_new'] = str(newest)
                health.update(error='', last_success=str(observed),
                              trip='waiting' if state['trip'] and state['trip']['stop'] else 'driving' if state['trip'] else 'idle',
                              charge='charging' if state['charge'] else 'idle' if state['last'] and state['last']['charging'] is False else 'unknown',
                              signals=json.dumps(state['last']['signals'], ensure_ascii=False) if state['last'] else '{}')
                self.auth_failure_alert.recovered()
                self.failures = 0
                def reminder_guard():
                    current_binding = load(self.root / 'monitor-binding.json').get('vehicle_key')
                    if session_scope(load(self.session_path)) != session_scope(session) or current_binding != binding:
                        raise ApiError('账号会话或绑定车辆已变化，本次自定义提醒已取消')
                reminder_sender = (FallbackSender(self.alert_sender, self.sender, compact_bark_times)
                                   if self.alert_sender is not None else self.sender)
                self.reminder_sender = reminder_sender
                self.reminders.observe(account_scope(session), binding, raw, observed,
                                       sender=reminder_sender, guard=reminder_guard)
                self.analysis_input = (session_scope(session), binding, observed)
        except RateLimited as exc:
            delay = max(60, exc.seconds)
            health.update(status='cooldown', error='接口限流，等待冷却')
        except ApiError as exc:
            error = str(exc)
            if exc.retry_after:
                delay = max(interval, exc.retry_after)
                health.update(status='cooldown', error=error[:150])
            elif any(token in error for token in ('网络或 TLS', 'HTTP 5', '并发锁')):
                self.failures += 1
                delay = min(900, 60 * 2 ** min(self.failures, 4))
                health.update(status='retrying', error=error[:150])
            else:
                self.blocked_fingerprint = fingerprint
                health.update(status='blocked', error=error[:150])
                self.auth_failure_alert.blocked(error)
        # Storage errors escape and stop the worker, never inventing transitions.
        self.monitor.deliver(self.sender, now, self.alert_sender)
        health['interval'] = str(delay)
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
                        print('统一采集已启动：正常采集每 %d 秒（含停车）；充电起止通知。' % read_settings(root)[1], flush=True)
                        collection_loop(runner, stop, once)
                    finally:
                        runner.insight_worker.close()
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
