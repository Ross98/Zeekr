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
import uuid

from .client import Client
from .cli import find_vins
from .errors import ApiError, RateLimited, RequestDeferred
from .monitor import Monitor
from .vehicle_state import decode
from .geocoding import AmapGeocoder
from .focused_trip_image import FocusedTripImage
from .profiles import vehicle_profile
from .notifications import BarkSender, FallbackSender, WeComSender, compact_bark_times, bark_channel
from .storage import DEFAULT_PATH, load, save
from .snapshots import SnapshotStore, session_scope
from .storage_health import StorageHealth
from .personal_store import PersonalStore, account_scope
from .commute_tags import CommuteTags
from .place_tag_rules import PlaceTagRules
from .custom_reminders import Reminders
from .tyre_notifications import TyreNotifications, ObservationCancelled
from .sampling import read_settings, read_request_settings, save_settings, SamplingUnavailable
from .query_policy import QueryPolicy
from .archive_reader import ArchiveReader
from .automatic_insights import Analyzer, InsightCache, InsightWorker
from .system_notifications import AuthFailureAlert
from .collection_incidents import CollectionIncidents
from .refresh_recovery import RefreshDriver


def enable_sampling(root):
    save_settings(root, True)


def sampling_enabled(root):
    return read_settings(root)[0]


class CollectionCancelled(RequestDeferred):
    """A background gateway request was cancelled before transport began."""


def collection_loop(runner, stop, once=False):
    """One owner; control changes are noticed within one second without querying."""
    deadline = 0
    previous = None
    previous_interval = None
    finished_at, delay = 0, None
    normal_wait = False
    runner.stop=stop
    while not stop.is_set():
        delivery=getattr(runner,'delivery_process',None)
        if delivery is not None:delivery.ensure_running()
        enabled, interval = read_settings(runner.root)
        if interval != previous_interval and normal_wait:
            # Reschedule normal collection only; a setting change cannot shorten
            # network backoff or a server cooldown.
            deadline = finished_at + interval
        previous_interval = interval
        if enabled != previous or time.monotonic() >= deadline:
            delay = runner.tick()
            if not stop.is_set():runner.start_analysis()
            normal_wait = delay == interval and runner.health().get('status') not in ('cooldown', 'retrying', 'blocked')
            finished_at = time.monotonic()
            deadline = finished_at + delay
            previous = enabled
            if once:
                if not stop.is_set():runner.deliver_once()
                break
        stop.wait(1)


def background(session_path, stop):
    """Web fallback shares the monitor lock with the standalone service."""
    root = Path(session_path).parent
    while not stop.is_set():
        try:
            with process_lock(root / 'monitor.lock'):
                runner = Runner(session_path)
                from .delivery_runtime import DeliveryProcess
                delivery = DeliveryProcess(session_path)
                try:
                    runner.delivery_process=delivery
                    collection_loop(runner, stop)
                finally:
                    delivery.close()
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
                        'last_new', 'trip', 'charge', 'data_change', 'state_time',
                        'refresh_status', 'incident_recording', 'derived_status')


def _safe_error(value):
    if not value:
        return ''
    text = str(value)
    if text=='凭据已更新，等待目标车辆接口恢复核对。':return text
    if '网关代码 1509' in text:
        return '车辆接口返回 1509，后台正在退避重试；期间记录可能不完整。'
    for category, tokens in (
        ('认证状态异常，请检查车辆连接。', ('登录', '认证', '401', '403', 'token')),
        ('接口暂不可用，后台将按策略处理。', ('网络', 'TLS', 'HTTP 5', 'HTTP 408', '限流', '冷却',
                                             '网关响应', '网关代码 unknown', '车辆列表响应', '有效车辆状态')),
        ('采集后台异常，请检查服务状态。', ())):
        if not tokens or any(token.lower() in text.lower() for token in tokens):
            return category


def read_status(root, vehicle=None, public=False):
    root = Path(root)
    health = load(root / 'monitor-health.json')
    if not health:
        return {'status': 'not_started', 'events': []}
    from .notification_health import service_heartbeat, number, STATES
    _, online = service_heartbeat(health,time.time()*1000,collector=True)
    source = ({key: health[key] for key in PUBLIC_HEALTH_FIELDS if key in health}
              if public else dict(health))
    if public:
        source['error'] = _safe_error(health.get('error'))
        if '网关代码 1509' in health.get('error', '') and health.get('gateway_reason'):
            from .client import gateway_reason
            source['error'] += ' 网关说明（脱敏）：' + gateway_reason(health['gateway_reason'])
    result = dict(source, online=online, events=[])
    path = root / 'tracks.sqlite3'
    if path.exists():
        db = sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_events'").fetchone():
                return result
            has_alerts = bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_event_alerts'").fetchone())
            alert_columns = ',a.delivery,a.error' if has_alerts else ',NULL,NULL'
            alert_join = ' LEFT JOIN monitor_event_alerts a ON a.event_id=e.id' if has_alerts else ''
            has_media = bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_event_media'").fetchone())
            alert_columns += ',m.delivery,m.error' if has_media else ',NULL,NULL'
            if has_media:alert_join += ' LEFT JOIN monitor_event_media m ON m.event_id=e.id'
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
                delivery_states=STATES|{'retry','unknown'}
                def delivery(value):
                    if value is None:return None
                    return value if isinstance(value,str) and value in delivery_states else 'unknown'
                result['events'] = [dict(kind=r[0] if r[0] in ('trip_start','trip_end','charge_start','charge_end') else 'vehicle_event',
                                         delivery=delivery(r[1]), error=_safe_error(r[2]), created=number(r[3]),
                                         alert_delivery=delivery(r[4]), alert_error=_safe_error(r[5]),
                                         image_delivery=delivery(r[6]), image_error='图片投递需要检查。' if r[7] else '') for r in rows]
            else:
                result['events'] = [dict(kind=r[0], summary=json.loads(r[1]), delivery=r[2], error=r[3], created=r[4],
                                         alert_delivery=r[5], alert_error=r[6],image_delivery=r[7],image_error=r[8]) for r in rows]
        finally:
            db.close()
    return result


class Runner:
    def __init__(self, session_path=DEFAULT_PATH, vehicle=None, client_factory=Client, sender=None,
                 active_codes=(), stopped_codes=(), alert_sender=None, refresh_driver=None):
        self.session_path = Path(session_path)
        self.root = self.session_path.parent
        if vehicle is not None and (type(vehicle) is not int or vehicle < 1):
            raise ValueError('车辆序号必须为正整数')
        if set(active_codes) & set(stopped_codes):
            raise ValueError('充电与停止状态码不可重叠')
        self.vehicle = vehicle
        self.client_factory = ((lambda session: Client(session, query_policy=QueryPolicy(self.root / 'queries.sqlite3'),
                                                      request_guard=self._guard_collection_request))
                               if client_factory is Client else client_factory)
        self.monitor = Monitor(self.root / 'tracks.sqlite3', active_codes, stopped_codes,
                               address_resolver=AmapGeocoder(self.root / 'amap-geocoding.json'),
                               map_renderer=FocusedTripImage(self.root / 'road-networks'))
        self.sender = sender if sender is not None else WeComSender(self.root / 'wecom-webhook.json')
        self.alert_sender = (alert_sender if alert_sender is not None else
                             BarkSender(self.root / 'bark.json') if sender is None else None)
        self.reminder_sender = (FallbackSender(bark_channel(self.alert_sender,'reminder'), self.sender, compact_bark_times)
                                if self.alert_sender is not None else self.sender)
        self.auth_failure_alert = AuthFailureAlert(self.root, self.alert_sender)
        self.incidents = CollectionIncidents(self.root)
        self.refresh_driver = refresh_driver if refresh_driver is not None else RefreshDriver(self.session_path,client_factory=self.client_factory)
        self.storage_health = StorageHealth(self.root, self.sender, self.alert_sender)
        self.reminders = Reminders(PersonalStore(self.root / 'personal.sqlite3'))
        self.tyre_notifications = TyreNotifications(self.reminders.store)
        self.commute_tags = CommuteTags(self.reminders.store, self.root / 'tracks.sqlite3')
        self.place_tag_rules = PlaceTagRules(self.reminders.store, self.root / 'tracks.sqlite3')
        self.blocked_fingerprint = None
        self.failures = 0
        self.analysis_input = None
        self.insight_worker = InsightWorker(
            Analyzer(self.root / 'tracks.sqlite3', ArchiveReader(self.root / 'snapshot-archive')),
            InsightCache(self.root / 'automatic-insights.json'))

    def deliver_once(self,now=None):
        from .delivery_runtime import DeliveryWorker
        worker=DeliveryWorker(self.session_path,sender=self.sender,alert_sender=self.alert_sender)
        worker.tick(now=now,image_limit=10,budget_seconds=30)

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

    def _guard_collection_request(self):
        stop=getattr(self,'stop',None)
        # Settings I/O can take time; check shutdown again immediately after it.
        if (stop is not None and stop.is_set() or not read_request_settings(self.root)[0]
                or stop is not None and stop.is_set()):
            raise CollectionCancelled('后台采集已暂停或正在退出，未发送网络请求。',retry_after=1)

    def _mark_sampling_gap(self,health):
        self.monitor.mark_sampling_gap(load(self.root/'monitor-binding.json').get('vehicle_key'))
        # Persist beyond gap_pending: optional rule processing can lag behind
        # the first accepted vehicle observation, or resume in another process.
        if health.get('gap_pending')!='true' or not health.get('sampling_epoch'):
            health['sampling_epoch']=uuid.uuid4().hex
        health['gap_pending']='true'

    def tick(self, now=None):
        self.analysis_input = None
        live_clock = now is None
        now = int(time.time() * 1000) if now is None else now
        health = self.health()
        health.update(heartbeat=str(now))
        enabled, interval = read_settings(self.root)
        delay = interval
        fingerprint = None
        observation_processed = False
        if not enabled:
            if health.get('status')!='paused' or health.get('gap_pending')!='true':
                self._mark_sampling_gap(health)
            health.update(status='paused', error='', interval=str(interval), next_check=str(now + interval * 1000))
            save(self.root / 'monitor-health.json', health)
            return interval
        try:
            session = load(self.session_path)
            fingerprint = hashlib.sha256(json.dumps(session, sort_keys=True).encode()).hexdigest()
            if not health.get('gateway_retry') and '网关代码 1509' in health.get('error', ''):
                self._mark_sampling_gap(health)
            retry = json.loads(health.get('gateway_retry', '{}'))
            if retry.get('session') == fingerprint and now < retry.get('next_at', 0):
                delay = max(1, (retry['next_at'] - now + 999) // 1000)
                health.update(status='retrying', interval=str(delay), next_check=str(retry['next_at']))
                save(self.root / 'monitor-health.json', health)
                return delay
            if retry and retry.get('session') != fingerprint:
                health.pop('gateway_retry', None)
            if self.blocked_fingerprint == fingerprint:
                health['status'] = 'blocked'
            else:
                if not session.get('accessToken'):
                    raise ApiError('尚未登录，请更新车辆会话后恢复监控')
                client = self.client_factory(session)
                vehicles = client.vehicles()
                self._guard_collection_request()
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
                snapshot_store = SnapshotStore(self.root / 'snapshots.sqlite3')
                publication = snapshot_store.publish(
                    session_scope(session), binding, raw, observed, fetched_at=fetched_at, source='monitor', owner_key=account_scope(session))
                if publication['change'] == 'superseded':
                    accepted = snapshot_store.read(session_scope(session),binding)
                    if accepted is None:
                        raise ApiError('共享快照已变化，稍后重试。',retryable=True)
                    raw = accepted['raw']
                profile = vehicle_profile(binding, choices.index(vin) + 1, len(choices))
                health['status'] = self.monitor.observe(binding, raw, observed,
                    battery_capacity_kwh=profile.get('battery_capacity_kwh'), profile=profile,
                    track_gap_seconds=0 if health.get('gap_pending') == 'true' else 180)
                observation_processed = True
                point = decode(raw, self.monitor.active_codes, self.monitor.stopped_codes)
                health.update(data_change=publication['change'],
                              state_time=str(int(point['time'])) if point['time'] is not None else '')
                # A repeated old parking snapshot describes the last known state,
                # not a collection failure or a new observation for event logic.
                # Sleeping cars can omit valid speed; P plus power-off is still
                # evidence for the last known parking state, never current state.
                if (health['status'] == 'stale' and publication['change'] == 'repeat'
                        and point['time'] is not None and observed - point['time'] > 180000
                        and point['off'] is True and point['charging'] is False
                        and (point['speed'] == 0
                             or point['speed'] is None and point['gear'] == 'P')):
                    health['status'] = 'parked_waiting'
                state = self.monitor.status(binding)
                # Parking uses the same cadence, so starting a trip stays visible.
                if health['status'] == 'fresh':
                    if self.monitor.tracks.record(binding, raw, observed,
                                                  0 if health.get('gap_pending') == 'true' else 180):
                        health['last_new'] = str(observed)
                    health.pop('gap_pending', None)
                with self.monitor.tracks.connect() as db:
                    newest = db.execute('SELECT MAX(observed_time) FROM observations WHERE vehicle=?', (binding,)).fetchone()[0]
                if newest is not None:
                    health['last_new'] = str(newest)
                health.update(error='', last_success=str(observed),
                              trip='waiting' if state['trip'] and state['trip']['stop'] else 'driving' if state['trip'] else 'idle',
                              charge='charging' if state['charge'] else 'idle' if state['last'] and state['last']['charging'] is False else 'unknown',
                              signals=json.dumps(state['last']['signals'], ensure_ascii=False) if state['last'] else '{}')
                outcome=getattr(client,'query_outcome',None)
                actual_success=(outcome is None or outcome.actual_request and not outcome.cache_hit
                                and outcome.operation=='status' and outcome.schema_valid
                                and outcome.success_code in ('1000','000000'))
                if actual_success:
                    self.auth_failure_alert.recovered()
                    health.pop('gateway_retry', None)
                    try:self.refresh_driver.coordinator.confirm_status(session,outcome)
                    except (ApiError,OSError,ValueError,sqlite3.Error):health['refresh_status']='storage_error'
                try:
                    self.incidents.success(account_scope(session),binding,session_scope(session),outcome,observed,
                                           int(point['time']) if point['time'] is not None else None)
                    health.pop('incident_recording',None)
                except (ApiError,OSError,ValueError,sqlite3.Error):health['incident_recording']='unavailable'
                self.failures = 0
                def reminder_guard():
                    current_binding = load(self.root / 'monitor-binding.json').get('vehicle_key')
                    if session_scope(load(self.session_path)) != session_scope(session) or current_binding != binding:
                        raise ApiError('账号会话或绑定车辆已变化，本次自定义提醒已取消')
                def tyre_guard():
                    reminder_guard()
                    if not sampling_enabled(self.root):
                        raise ObservationCancelled()
                # Rule/configuration errors are not vehicle authentication failures.
                # Core storage errors still escape; each optional update keeps its guard.
                health['derived_status']='ready'
                for update in (
                    lambda:self.reminders.observe(account_scope(session),binding,raw,observed,sender=None,guard=reminder_guard,
                                                 sampling_epoch=health.get('sampling_epoch')),
                    lambda:self.tyre_notifications.observe(account_scope(session),binding,raw,observed,bark=None,wecom=None,guard=tyre_guard,
                                                          sampling_epoch=health.get('sampling_epoch')),
                    lambda:self.commute_tags.collect(account_scope(session),binding,observed,guard=reminder_guard),
                    lambda:self.place_tag_rules.collect(account_scope(session),binding,observed,guard=reminder_guard)):
                    try:update()
                    except ObservationCancelled:pass
                    except (ApiError,ValueError):health['derived_status']='unavailable'
                self.analysis_input = (session_scope(session), binding, observed)
        except SamplingUnavailable as exc:
            self._mark_sampling_gap(health)
            health.update(status='unavailable',error=str(exc))
        except CollectionCancelled:
            self._mark_sampling_gap(health)
            stopping=getattr(self,'stop',None)
            health.update(status='stopped' if stopping is not None and stopping.is_set() else 'paused',error='')
        except RateLimited as exc:
            if not observation_processed:self._mark_sampling_gap(health)
            delay = max(60, exc.seconds)
            health.update(status='cooldown', error='接口限流，等待冷却')
        except ApiError as exc:
            error = str(exc)
            if not observation_processed and not isinstance(exc,RequestDeferred):
                self._mark_sampling_gap(health)
            if exc.gateway_code == '1509':
                retry = json.loads(health.get('gateway_retry', '{}'))
                if retry.get('session') != fingerprint:
                    retry = dict(session=fingerprint, first_at=now, attempts=0)
                retry['attempts'] += 1
                delay = min(300, 60 * 2 ** min(retry['attempts'] - 1, 3))
                finished = int(time.time() * 1000) if live_clock else now
                retry['next_at'] = finished + delay * 1000
                health.update(status='retrying', error=error[:400], gateway_retry=json.dumps(retry),
                              gateway_reason=exc.gateway_reason or '', gateway_error_at=str(now), gap_pending='true')
                self.auth_failure_alert.record_failure(exc.gateway_code, exc.gateway_reason, now)
                incident=None
                try:
                    incident=self.incidents.failure(account_scope(session),
                        load(self.root/'monitor-binding.json').get('vehicle_key','unbound'),session_scope(session),now,
                        int(health['state_time']) if health.get('state_time') else None,
                        int(health['last_success']) if health.get('last_success') else None)
                    health.pop('incident_recording',None)
                except (ApiError,OSError,ValueError,sqlite3.Error):health['incident_recording']='unavailable'
                eligibility=(dict(incident,attempts=min(incident['attempts'],retry['attempts']),
                                  opened_at=max(incident['opened_at'],retry['first_at'])) if incident else None)
                recovery=self.refresh_driver.attempt(session,eligibility,now)
                recovery_at=int(time.time()*1000) if live_clock else now
                health['refresh_status']=recovery.kind
                if recovery.kind=='refreshed':
                    delay=1
                    health['error']='凭据已更新，等待目标车辆接口恢复核对。'
                elif recovery.kind in ('deferred','rate_limited'):
                    delay=max(delay,recovery.wait_seconds)
                    retry['next_at']=recovery_at+delay*1000
                    health['gateway_retry']=json.dumps(retry)
                if incident and recovery.kind in ('refreshed','manual_required','uncertain','rate_limited','storage_error'):
                    try:self.incidents.classify(incident['id'],recovery.kind,recovery_at)
                    except (ApiError,OSError,ValueError,sqlite3.Error):health['incident_recording']='unavailable'
                if recovery.kind in ('manual_required','uncertain'):
                    self.auth_failure_alert.blocked(error,now,manual=True,incident_id=incident['id'] if incident else None,
                                                    reason=exc.notification_reason)
                elif retry['attempts'] >= 3 and now - retry['first_at'] >= 600000:
                    self.auth_failure_alert.blocked(error,now,incident_id=incident['id'] if incident else None,
                                                    reason=exc.notification_reason)
            elif exc.retry_after:
                delay = max(interval, exc.retry_after)
                health.update(status='cooldown', error=error[:150])
            elif exc.retryable or any(token in error for token in ('网络或 TLS', 'HTTP 5', '并发锁')):
                self.failures += 1
                delay = max(interval, min(60, 20 * 2 ** min(self.failures, 2)))
                health.update(status='retrying', error=error[:150])
                code=exc.network_code if exc.network_code in ('dns','timeout','certificate','tls','connection_refused','connection') else None
                if code:health.update(network_error_code=code,network_error_at=str(now))
                try:
                    self.incidents.failure(account_scope(session),
                        load(self.root/'monitor-binding.json').get('vehicle_key','unbound'),session_scope(session),now,
                        int(health['state_time']) if health.get('state_time') else None,
                        int(health['last_success']) if health.get('last_success') else None,
                        kind='network:'+code if code else 'request_retryable')
                    health.pop('incident_recording',None)
                except (ApiError,OSError,ValueError,sqlite3.Error):health['incident_recording']='unavailable'
            else:
                self.blocked_fingerprint = fingerprint
                health.update(status='blocked', error=error[:150])
                self.auth_failure_alert.blocked(error,now,reason=exc.notification_reason)
        # Storage errors escape and stop the worker, never inventing transitions.
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
                    from .delivery_runtime import DeliveryProcess
                    delivery=None if once else DeliveryProcess(session_path)
                    runner.delivery_process=delivery
                    try:
                        print('统一采集已启动：正常采集每 %d 秒（含停车）；充电起止通知。' % read_settings(root)[1], flush=True)
                        collection_loop(runner, stop, once)
                    finally:
                        if delivery is not None:delivery.close()
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
