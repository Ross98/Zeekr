"""Loopback-only Web UI and shared background cached-position collection."""
import hashlib
import hmac
import os
from http.cookies import SimpleCookie
from .auth import WebAuth
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

from .client import ApiError, Client
from .cli import find_vins
from .storage import DEFAULT_PATH, load, save
from .summary import updated_at
from .tracks import TrackStore, day_bounds, empty_route
from .trips import TripStore
from .trip_management import TripRecordManager
from .web_model import build_model, parse_location
from .field_reviews import FieldReviewStore
from .profiles import vehicle_profile
from .energy import read_attainment
from .history import HistoryClient, HistoryError, connection_status, day_window, integer
from .snapshots import SnapshotStore, session_scope
from .events import EventStore
from .storage_management import StorageManager
from .storage_health import StorageHealth, severity
from .charging_analytics import ChargingAnalytics
from .vehicle_parameters import parameters
from .archive_reader import ArchiveReader
from .parking_analytics import ParkingAnalytics
from .usage_reports import UsageReports
from .personal_store import PersonalStore, account_scope
from .charge_ledger import ChargeLedger
from .custom_reminders import Reminders
from .trip_tags import TripTags
from .charge_comparison import ChargeComparison
from .parameter_experiments import ParameterExperiments
from .usage_calendar import UsageCalendar
from .vehicle_life import VehicleLife
from .data_quality import DataQuality
from .trip_cards import TripCards

STATIC = Path(__file__).parent / 'static'


class RefreshBusy(ValueError):
    """Another refresh is already responsible for this sampling interval."""


class App:
    def __init__(self, session_path=DEFAULT_PATH, database_path=None, client_factory=Client):
        self.session_path = Path(session_path)
        self.database_path = Path(database_path or self.session_path.parent / 'tracks.sqlite3')
        self.field_review_store = FieldReviewStore(self.database_path.with_name("field-reviews.sqlite3"))
        self.snapshot_store = SnapshotStore(self.session_path.parent / 'snapshots.sqlite3')
        self.event_store = EventStore(self.database_path)
        self.trip_store = TripStore(self.database_path)
        self.trip_manager = TripRecordManager(self.database_path)
        self.storage_manager = StorageManager(self.session_path.parent)
        self.charging_analytics = ChargingAnalytics(self.database_path)
        self.archive_reader = ArchiveReader(self.session_path.parent / 'snapshot-archive')
        self.usage_reports = UsageReports(self.database_path, self.archive_reader)
        self.personal_store = PersonalStore(self.session_path.parent / 'personal.sqlite3')
        self.charge_ledger = ChargeLedger(self.personal_store, self.database_path)
        self.reminders = Reminders(self.personal_store)
        self.trip_tags = TripTags(self.personal_store, self.database_path)
        self.charge_comparison = ChargeComparison(self.database_path)
        self.experiments = ParameterExperiments(self.personal_store, self.archive_reader)
        self.usage_calendar = UsageCalendar(self.database_path, self.archive_reader)
        self.vehicle_life = VehicleLife(self.personal_store)
        self.data_quality = DataQuality(self.archive_reader)
        self.trip_cards = TripCards(self.database_path)
        self.client_factory = client_factory
        self.request_key = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.refresh_lock = threading.Lock()
        self.history_lock = threading.Lock()
        self.history_selections = {}
        self.stop = threading.Event()
        self.model = None
        self.raw = None
        self.vehicle = 1
        self.vehicle_key = None
        self.vehicles = []
        self.read_at = None
        self.query_cached = False
        self.refresh_result = None
        self.next_query_at = None
        self.profile = None
        self.error = None
        self.store = None
        self.monitor_thread = None
        self.snapshot_revision = None
        self.session_key = None

    def _sync_session(self, session):
        """Invalidate in-memory vehicle data when its private session scope changes."""
        key = session_scope(session) if session and session.get('accessToken') else None
        if key == self.session_key:
            return
        self.session_key = key
        self.raw = self.model = self.profile = None
        self.vehicle, self.vehicle_key, self.vehicles = 1, None, []
        self.read_at = self.snapshot_revision = None
        self.query_cached = False
        self.refresh_result = self.next_query_at = self.error = None
        self.history_selections.clear()

    def _read_session(self):
        try:
            session = load(self.session_path)
        except ApiError:
            self._sync_session(None)
            raise
        self._sync_session(session)
        return session

    def start_monitor(self):
        from .monitor_runtime import background, enable_sampling
        enable_sampling(self.session_path.parent)
        self.monitor_thread = threading.Thread(target=background, args=(self.session_path, self.stop),
                                               name='zeekr-monitor', daemon=True)
        self.monitor_thread.start()

    def state(self):
        with self.lock:
            try:
                session = self._read_session()
                authenticated = bool(session.get('accessToken'))
                session_error = None
            except ApiError as exc:
                authenticated, session_error = False, str(exc)
                session = None
            if authenticated:
                self._restore_snapshot(session)
            try:
                from .monitor_runtime import read_status
                monitoring = read_status(self.session_path.parent,
                                         self.vehicle_key if authenticated and self.vehicle_key else None,
                                         public=True)
            except Exception:
                monitoring = {'status': 'unavailable', 'online': False, 'events': []}
            try:
                archives = self._store().vehicles() if self.database_path.exists() else []
                storage_error = None
            except Exception:
                archives, storage_error = [], '本地轨迹存储暂不可用。'
            from .monitor_runtime import sampling_enabled
            enabled = sampling_enabled(self.session_path.parent)
            status = ('paused' if not enabled else 'offline' if not monitoring.get('online') else
                      'failed' if monitoring.get('status') in ('blocked', 'unavailable') else 'active')
            try:
                field_reviews = self.field_review_store.read(self.vehicle_key)
            except Exception:
                field_reviews = {'vehicle': self.vehicle_key, 'revision': None, 'records': [],
                                 'error': '核实记录暂不可用，请重试；未修改已有记录。'}
            try:
                recent_events = (self.event_store.latest(self.vehicle_key)
                                 if authenticated and self.vehicle_key else
                                 {'trip_end': None, 'charge_end': None})
            except Exception:
                recent_events = {'trip_end': None, 'charge_end': None, 'error': '本地事件暂不可用。'}
            try:
                trip_revision = self.trip_manager.revision(self.vehicle_key) if authenticated and self.vehicle_key else None
            except Exception:
                trip_revision = None
            return {'field_reviews': field_reviews, 'request_key': self.request_key, 'authenticated': authenticated,
                    'insights_context': self._insights_context(),
                    'trip_records_revision': trip_revision,
                    'model': self.model, 'vehicle': self.vehicle, 'vehicles': self.vehicles,
                    'read_at': updated_at(self.read_at), 'read_time': self.read_at,
                    'query_cached': self.query_cached, 'refresh_result': self.refresh_result,
                    'snapshot_revision': self.snapshot_revision,
                    'next_query_at': self.next_query_at, 'profile': self.profile, 'archived_vehicles': archives,
                    'error': self.error or session_error or storage_error,
                    'recording': {'active': enabled, 'interval': 60,
                                  'effective_interval': int(monitoring.get('interval', 60)),
                                  'status': status, 'error': monitoring.get('error'),
                                  'last_sample': updated_at(monitoring.get('last_success')),
                                  'last_new': updated_at(monitoring.get('last_new'))},
                    'history': connection_status(session, self.vehicle_key) if authenticated else
                               {'status': 'authorization_required', 'message': '请先连接车辆账号。'},
                    'monitoring': monitoring, 'recent_events': recent_events,
                    'range_attainment': read_attainment(self.database_path, self.vehicle_key, self.profile),
                    'storage_bytes': self.database_path.stat().st_size if self.database_path.exists() else 0}

    def _restore_snapshot(self, session, vehicle=None):
        if not session.get('accessToken'):
            return
        try:
            binding = load(self.session_path.parent / 'monitor-binding.json').get('vehicle_key')
        except Exception:
            binding = self.vehicle_key
        key = self.vehicle_key or binding
        if not key:
            return
        snapshot = self.snapshot_store.read(session_scope(session), key, known_revision=self.snapshot_revision)
        if not snapshot:
            return
        self.vehicle_key = key
        self.raw = snapshot['raw']
        self.model = build_model(self.raw, vehicle=vehicle)
        self.read_at = snapshot['fetched_at']
        self.snapshot_revision = snapshot['revision']
        if self.profile is None:
            self.profile = vehicle_profile(key, self.vehicle, 1)
        if not self.vehicles:
            self.vehicles = [{'number': self.vehicle, 'label': '车辆 %d' % self.vehicle}]

    def _history_context(self):
        session = load(self.session_path)
        with self.lock:
            key = self.vehicle_key
        if key is None:
            raise HistoryError('vehicle_required', '请先刷新车辆状态，选择要查询的车辆。')
        status = connection_status(session, key)
        if status['status'] != 'ready':
            raise HistoryError(status['status'], status['message'])
        fingerprint = hashlib.sha256(json.dumps(session, sort_keys=True).encode()).hexdigest()
        return session, key, fingerprint

    def history(self, date, cursor=None):
        lower, upper = day_window(date)
        if cursor is not None:
            cursor = integer(cursor, lower, upper - 1)
        if not self.history_lock.acquire(blocking=False):
            return HistoryError('busy', '历史查询正在进行，请稍后重试。').result()
        try:
            session, vehicle, fingerprint = self._history_context()
            result = HistoryClient(session).day(date, cursor)
            # Do not deliver a result for a vehicle/account changed mid-request.
            if self._history_context()[1:] != (vehicle, fingerprint):
                raise HistoryError('selection_changed', '车辆或账号已切换，请重新查询。')
            now = time.monotonic()
            with self.lock:
                self.history_selections = {key: value for key, value in self.history_selections.items()
                                           if value['expires'] > now}
                for trip in result['trips']:
                    key = secrets.token_urlsafe(24)
                    self.history_selections[key] = {'vehicle': vehicle, 'session': fingerprint,
                        'id': trip.pop('id'), 'report_time': trip.pop('report_time'), 'expires': now + 3600}
                    trip['key'] = key
                while len(self.history_selections) > 200:
                    del self.history_selections[next(iter(self.history_selections))]
            return result
        except HistoryError as exc:
            return exc.result()
        except ApiError:
            return HistoryError('authorization_required', '无法读取本机会话，请检查连接配置。').result()
        finally:
            self.history_lock.release()

    def history_points(self, key):
        if not isinstance(key, str) or not key or len(key) > 100:
            raise ValueError('请选择已查询到的行程。')
        if not self.history_lock.acquire(blocking=False):
            return HistoryError('busy', '历史查询正在进行，请稍后重试。').result()
        try:
            session, vehicle, fingerprint = self._history_context()
            with self.lock:
                trip = self.history_selections.get(key)
            if (not trip or trip['vehicle'] != vehicle or trip['session'] != fingerprint
                    or trip['expires'] <= time.monotonic()):
                raise ValueError('行程选择已失效，请重新查询。')
            result = HistoryClient(session).points(trip['id'], trip['report_time'])
            if self._history_context()[1:] != (vehicle, fingerprint):
                raise HistoryError('selection_changed', '车辆或账号已切换，请重新查询。')
            return result
        except HistoryError as exc:
            # A changed vehicle must invalidate the old detail selection too.
            if exc.status == 'vehicle_mismatch':
                raise ValueError('行程选择已失效，请重新查询。') from None
            return exc.result()
        except ApiError:
            return HistoryError('authorization_required', '无法读取本机会话，请检查连接配置。').result()
        finally:
            self.history_lock.release()

    def refresh(self, vehicle):
        if type(vehicle) is not int or vehicle < 1:
            raise ValueError('请选择有效车辆序号。')
        if not self.refresh_lock.acquire(blocking=False):
            raise RefreshBusy('正在读取，请稍后。')
        client = None
        scope = None
        try:
            with self.lock:
                session = self._read_session()
                scope = session_scope(session)
                self._restore_snapshot(session)
            client = self.client_factory(session)
            vehicles = client.vehicles()
            if vehicle > len(vehicles):
                raise ValueError('车辆序号超出范围，或账号下没有可用车辆。')
            vins = find_vins(vehicles[vehicle - 1])
            if len(vins) != 1:
                raise ApiError('车辆未返回唯一有效 VIN。')
            vin = next(iter(vins))
            raw = client.status(vin)
            model = build_model(raw, vehicle=vehicles[vehicle - 1])
            with self.lock:
                if session_scope(self._read_session()) != scope:
                    raise ApiError('车辆会话已变化，请重新刷新状态。')
                key = hashlib.sha256(vin.encode()).hexdigest()
                previous_time = self.model.get('updated_time') if self.model and key == self.vehicle_key else None
                incoming_time = model['updated_time']
                fetched_at = getattr(client, "last_query_fetched_at", None)
                observed_at = int(time.time() * 1000)
                self.snapshot_store.publish(
                    scope, key, raw, observed_at,
                    fetched_at=int((fetched_at if fetched_at is not None else time.time()) * 1000), source='manual')
                self.vehicle, self.vehicle_key = vehicle, key
                self.profile = vehicle_profile(key, vehicle, len(vehicles))
                self.vehicles = [{'number': index, 'label': '车辆 %d' % index} for index in range(1, len(vehicles) + 1)]
                # Publish can reject old/undated responses, or the monitor can win
                # a concurrent update. Always render the store's accepted snapshot.
                self.snapshot_revision = None
                self._restore_snapshot(session, vehicle=vehicles[vehicle - 1])
                self.query_cached = bool(getattr(client, 'last_query_cached', False))
                self.next_query_at = getattr(client, 'next_query_at', None)
                self.refresh_result = ('cached' if self.query_cached else 'time_unknown' if incoming_time is None
                                       else 'new' if previous_time is None or incoming_time > previous_time else 'unchanged')
                self.error = None
                return self.state()
        except ApiError as exc:
            with self.lock:
                if self.session_key == scope:
                    self.error = str(exc)
                    self.next_query_at = getattr(client, 'next_query_at', self.next_query_at)
            raise
        finally:
            self.refresh_lock.release()

    def review_field(self, data):
        with self.lock:
            self._restore_snapshot(self._read_session())
            paths = {field['path'] for field in (self.model or {}).get('fields', [])}
            return self.field_review_store.update(self.vehicle_key, data, paths)

    def vehicle_parameters(self):
        with self.lock:
            current = self.state()  # Restore only the shared local snapshot; never refresh the cloud.
            result = parameters(self.raw, self.model)
            result.update(vehicle=current['vehicle'], vehicle_key=current['field_reviews']['vehicle'],
                          snapshot_revision=current['snapshot_revision'],
                          read_time=current['read_time'])
            return result

    def _archive_vehicle(self):
        if self.vehicle_key:
            return self.vehicle_key
        try:
            value = load(self.session_path.parent / 'monitor-binding.json').get('vehicle_key')
            return value if isinstance(value, str) and value else None
        except ApiError:
            return None

    def _insights_context(self):
        # A persisted binding alone cannot establish the new account's vehicle.
        vehicle = self.vehicle_key
        if not self.session_key or not vehicle:
            return None
        return hmac.new(self.request_key.encode(), (self.session_key + ':' + vehicle).encode(),
                        hashlib.sha256).hexdigest()

    def insights(self, operation, *args):
        with self.lock:
            session = self._read_session()
            if not session.get('accessToken'):
                raise ValueError('请先连接车辆账号。')
            self._restore_snapshot(session)
            if operation not in ('timeline','snapshot','compare','parking') and not self.vehicle_key:
                raise ValueError('等待当前账号的车辆缓存，旧账号绑定不能用于读取这些记录。')
            vehicle, context = self._archive_vehicle(), self._insights_context()
            handlers = {'timeline': self.archive_reader.timeline, 'snapshot': self.archive_reader.snapshot,
                        'trip-management': lambda scope, car, *query: self.trip_manager.query(car, *query),
                        'compare': self.archive_reader.compare,
                        'report': self.usage_reports.query,
                        'calendar': self.usage_calendar.query,
                        'quality': self.data_quality.query,
                        'cards': lambda scope, car, date: self.trip_cards.query(car,date),
                        'life': lambda scope, car, date: self.vehicle_life.query(account_scope(session),car,date,self.raw,self.read_at),
                        'ledger': lambda scope, car, date: self.charge_ledger.query(account_scope(session),car,date),
                        'rules': lambda scope, car: self.reminders.query(account_scope(session),car),
                        'trip-tags': lambda scope, car, date: self.trip_tags.query(account_scope(session),car,date),
                        'charge-options': lambda scope, car, date: self.charge_comparison.options(car,date),
                        'charge-comparison': lambda scope, car, a, b: self.charge_comparison.query(car,a,b),
                        'experiments': lambda scope, car: self.experiments.query(account_scope(session),car),
                        'experiment': lambda scope, car, identity: self.experiments.detail(account_scope(session),car,identity),
                        'parking': lambda scope, car, start, end: ParkingAnalytics(self.archive_reader).query(
                            scope, car, start, end, (self.profile or {}).get('battery_capacity_kwh'))}
            result = handlers[operation](session_scope(session), vehicle, *args)
            current_session = self._read_session()
            if session_scope(current_session) != session_scope(session) or context != self._insights_context():
                raise ValueError('账号或车辆已切换，请重新读取。')
            result['context'] = context
            return result

    def manage_trips(self, operation, data, owner):
        with self.lock:
            session = self._read_session()
            if not session.get('accessToken'):
                raise ValueError('请先连接车辆账号。')
            self._restore_snapshot(session)
            context = self._insights_context()
            if not context or data.get('context') != context:
                raise ValueError('账号或车辆已切换，请重新读取行程。')
            fingerprint = session_scope(session)
            bound_owner = context+':'+owner
            def guard():
                if session_scope(load(self.session_path)) != fingerprint or self._insights_context() != context:
                    raise ValueError('操作期间账号或车辆已切换，本次修改已取消。')
            if operation == 'preview':
                result = self.trip_manager.preview(self.vehicle_key, data.get('action'), data.get('ids'),
                                                   data.get('revision'), bound_owner)
                guard()
            elif operation == 'execute':
                result = self.trip_manager.execute(data.get('token'), bound_owner, guard=guard)
            else:
                raise ValueError('行程管理操作无效。')
            result['context'] = context
            return result

    def update_insight_record(self, operation, data):
        with self.lock:
            session = self._read_session()
            if not session.get('accessToken'):
                raise ValueError('请先连接车辆账号。')
            self._restore_snapshot(session)
            context, vehicle = self._insights_context(), self._archive_vehicle()
            if not context or data.get('context') != context:
                raise ValueError('账号或车辆已切换，请重新加载。')
            fingerprint = session_scope(session)
            def guard():
                if session_scope(load(self.session_path)) != fingerprint or self._insights_context() != context:
                    raise ValueError('保存期间账号或车辆已切换；本次修改已取消。')
            if operation == 'rule-preview':
                result = self.reminders.preview(account_scope(session),vehicle,data,self.raw,int(time.time()*1000))
                guard()
            else:
                manager = {'ledger':self.charge_ledger,'rules':self.reminders,'trip-tags':self.trip_tags,
                           'experiments':self.experiments,'life':self.vehicle_life}[operation]
                extra = {'scope':session_scope(session)} if operation=='experiments' else {}
                result = manager.update(account_scope(session), vehicle, data, guard=guard,**extra)
            result['context'] = context
            return result

    def _store(self):
        if self.store is None:
            self.store = TrackStore(self.database_path)
        return self.store

    def recording(self, active, interval):
        if type(active) is not bool or type(interval) is not int or interval != 60:
            raise ValueError('统一采集默认间隔为 60 秒，确认停车后自动降至 300 秒。')
        save(self.session_path.parent / 'sampling.json', {'enabled': 'true' if active else 'false'})
        return self.state()

    def location(self):
        with self.lock:
            self._restore_snapshot(self._read_session())
            result = parse_location(self.raw or {})
            result['read_at'] = updated_at(self.read_at)
            return result

    def _local_vehicle(self, archive=None):
        self._restore_snapshot(self._read_session())
        selected = self.vehicle_key
        if not selected:
            try:
                selected = load(self.session_path.parent / 'monitor-binding.json').get('vehicle_key')
            except ApiError:
                raise ValueError('本地车辆绑定无法读取。') from None
        if selected is not None and not isinstance(selected, str):
            raise ValueError('本地车辆绑定无效。')
        if not selected:
            vehicles = self.trip_store.vehicles()
            if len(vehicles) > 1:
                raise ValueError('本地存在多辆车辆，无法确定当前车辆。')
            selected = next(iter(vehicles), None)
        if archive is not None and (not archive or archive != selected):
            raise ValueError('所选本地车辆不是当前车辆。')
        return selected

    def tracks(self, date, archive=None, trip=None):
        with self.lock:
            day_bounds(date)
            selected = self._local_vehicle(archive)
            if trip is not None:
                start, end = self.trip_store.bounds(selected, trip, date)
                return self.trip_store.tracks.between(selected, start, end, date)
            if not self.database_path.exists():
                return empty_route(date)
            return self.trip_store.tracks.day(selected, date)

    def trips(self, date, cursor=None):
        with self.lock:
            return self.trip_store.query(self._local_vehicle(), date, cursor)

    def events(self, date, kind, cursor=None):
        with self.lock:
            self._restore_snapshot(self._read_session())
            if not self.vehicle_key:
                raise ValueError('请先选择车辆。')
            return self.event_store.query(self.vehicle_key, date, kind, cursor=cursor)

    def storage_status(self):
        health = StorageHealth(self.session_path.parent)
        previous = health.cached()
        current = health.measure()
        current['status'] = severity(current, previous.get('status'))
        return {'current': current, 'monitor': previous}

    def charging_session(self, selection):
        with self.lock:
            self._restore_snapshot(self._read_session())
            return self.charging_analytics.session(self.vehicle_key, selection)

    def charging_series(self, selection, view):
        with self.lock:
            self._restore_snapshot(self._read_session())
            return self.charging_analytics.series(self.vehicle_key, selection, view)

    def charging_process(self, selection, view):
        with self.lock:
            self._restore_snapshot(self._read_session())
            return self.charging_analytics.process(self.vehicle_key, selection, view)

    def charging_statistics(self, days, mode):
        with self.lock:
            self._restore_snapshot(self._read_session())
            try:
                parsed = int(days)
            except (TypeError, ValueError):
                raise ValueError('充电统计范围无效。') from None
            return self.charging_analytics.statistics(self.vehicle_key, parsed, mode)

    def close(self):
        self.stop.set()
        if self.monitor_thread is not None:
            self.monitor_thread.join(timeout=1.5)


def make_server(app, port=8765, auth=None, public_origin=None):
    if public_origin and (not auth or not public_origin.startswith("https://") or urlsplit(public_origin).path):
        raise ValueError("Public origin requires HTTPS and authentication")
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, format, *args):
            pass  # URLs and payloads may contain private information.

        def permitted(self, mutation=False):
            hosts = {'127.0.0.1:%d' % self.server.server_port, 'localhost:%d' % self.server.server_port}
            host = self.headers.get('Host', '')
            if public_origin:
                hosts.add(urlsplit(public_origin).netloc)
            if host not in hosts or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return False
            expected = public_origin if public_origin and host == urlsplit(public_origin).netloc else 'http://' + host
            origin = self.headers.get('Origin')
            if origin is not None and origin != expected:
                return False
            return not mutation or (origin == expected and
                secrets.compare_digest(self.headers.get('X-Request-Key', ''), app.request_key))

        def token(self):
            try:
                cookies = SimpleCookie(self.headers.get('Cookie', ''))
                return cookies['zeekr_session'].value if 'zeekr_session' in cookies else ''
            except Exception:
                return ''

        def signed_in(self):
            return auth is None or auth.valid(self.token())

        def auth_post(self):
            host = self.headers.get('Host', '')
            expected = public_origin if public_origin and host == urlsplit(public_origin).netloc else 'http://' + host
            if not self.permitted() or self.headers.get('Origin') != expected:
                return self.send(403, {'error': '请求来源无效。'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError()
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError()
            except (ValueError, OSError):
                return self.send(400, {'error': '请求格式无效。'})
            secure = '; Secure' if expected.startswith('https://') else ''
            if self.path == '/auth/logout':
                auth.logout(self.token())
                return self.send(200, {}, cookie='zeekr_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0' + secure)
            if auth.limited():
                return self.send(429, {'error': '尝试过多，请五分钟后再试。'})
            token = auth.login(data.get('password'))
            if not token:
                return self.send(401, {'error': '密码错误或尝试过多。'})
            return self.send(200, {}, cookie='zeekr_session=' + token + '; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200' + secure)

        def send(self, status, value, content_type='application/json; charset=utf-8', cookie=None):
            payload = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            try:
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                # Closing a tab can cancel an in-flight response. The client is
                # already gone: do not retry with a 500 or alter application state.
                self.close_connection = True

        def do_GET(self):
            if not self.permitted():
                return self.send(403, {'error': '仅允许本机同源访问。'})
            if self.path in ('/login.js', '/login.css', '/theme.js', '/theme.css'):
                name = self.path[1:]
                return self.send(200, (STATIC / name).read_bytes(), 'text/javascript' if name.endswith('.js') else 'text/css')
            if not self.signed_in():
                if self.path == '/':
                    return self.send(200, (STATIC / 'login.html').read_bytes(), 'text/html; charset=utf-8')
                return self.send(401, {'error': '请先登录。'})
            url = urlsplit(self.path)
            try:
                if url.path == '/api/state':
                    return self.send(200, app.state())
                if url.path == '/api/vehicle/parameters':
                    return self.send(200, app.vehicle_parameters())
                if url.path.startswith('/api/insights/'):
                    query = parse_qs(url.query, keep_blank_values=True)
                    value = lambda name, default='': query.get(name, [default])[0]
                    if url.path == '/api/insights/timeline':
                        return self.send(200, app.insights('timeline', value('date'), value('cursor', None)))
                    if url.path == '/api/insights/snapshot':
                        return self.send(200, app.insights('snapshot', value('id')))
                    if url.path == '/api/insights/compare':
                        return self.send(200, app.insights('compare', value('before'), value('after')))
                    if url.path == '/api/insights/parking':
                        return self.send(200, app.insights('parking', value('start'), value('end')))
                    if url.path == '/api/insights/report':
                        return self.send(200, app.insights('report', value('period'), value('date')))
                    if url.path == '/api/insights/calendar':
                        return self.send(200, app.insights('calendar',value('date')))
                    if url.path == '/api/insights/life':
                        return self.send(200, app.insights('life',value('date')))
                    if url.path == '/api/insights/quality':
                        return self.send(200, app.insights('quality',value('start'),value('end')))
                    if url.path == '/api/insights/cards':
                        return self.send(200, app.insights('cards',value('date')))
                    if url.path == '/api/insights/ledger':
                        return self.send(200, app.insights('ledger', value('date')))
                    if url.path == '/api/insights/rules':
                        return self.send(200, app.insights('rules'))
                    if url.path == '/api/insights/trip-tags':
                        return self.send(200, app.insights('trip-tags',value('date')))
                    if url.path == '/api/insights/charge-comparison/options':
                        return self.send(200, app.insights('charge-options',value('date')))
                    if url.path == '/api/insights/charge-comparison':
                        return self.send(200, app.insights('charge-comparison',value('a'),value('b')))
                    if url.path == '/api/insights/experiments':
                        return self.send(200, app.insights('experiments'))
                    if url.path == '/api/insights/experiments/detail':
                        return self.send(200, app.insights('experiment',value('id')))
                if url.path == '/api/storage':
                    return self.send(200, app.storage_status())
                if url.path == '/api/storage/archives':
                    return self.send(200, app.storage_manager.inventory())
                if url.path == '/api/location':
                    return self.send(200, app.location())
                if url.path == '/api/history':
                    query = parse_qs(url.query, keep_blank_values=True)
                    return self.send(200, app.history(query.get('date', [''])[0], query.get('cursor', [None])[0]))
                if url.path == '/api/history/points':
                    query = parse_qs(url.query, keep_blank_values=True)
                    return self.send(200, app.history_points(query.get('trip', [''])[0]))
                if url.path == '/api/tracks':
                    query = parse_qs(url.query, keep_blank_values=True)
                    return self.send(200, app.tracks(query.get('date', [''])[0], query.get('vehicle', [None])[0],
                                                     trip=query.get('trip', [None])[0]))
                if url.path == '/api/trips':
                    query = parse_qs(url.query, keep_blank_values=True)
                    return self.send(200, app.trips(query.get('date', [''])[0], query.get('cursor', [None])[0]))
                if url.path == '/api/trips/manage':
                    query = parse_qs(url.query, keep_blank_values=True)
                    return self.send(200, app.insights('trip-management', query.get('start', [''])[0],
                                                       query.get('end', [''])[0], query.get('status', ['active'])[0],
                                                       query.get('cursor', [None])[0]))
                if url.path == '/api/events':
                    query = parse_qs(url.query, keep_blank_values=True)
                    return self.send(200, app.events(query.get('date', [''])[0],
                                                     query.get('kind', [''])[0],
                                                     query.get('cursor', [None])[0]))
                if url.path == '/api/charging/session':
                    query = parse_qs(url.query, keep_blank_values=True)
                    return self.send(200, app.charging_session(query.get('id', [''])[0]))
                if url.path == '/api/charging/series':
                    query = parse_qs(url.query, keep_blank_values=True)
                    return self.send(200, app.charging_series(query.get('id', [''])[0],
                                                               query.get('view', [''])[0]))
                if url.path == '/api/charging/process':
                    query = parse_qs(url.query, keep_blank_values=True)
                    return self.send(200, app.charging_process(query.get('id', [''])[0],
                                                                query.get('view', [''])[0]))
                if url.path == '/api/charging/statistics':
                    query = parse_qs(url.query, keep_blank_values=True)
                    return self.send(200, app.charging_statistics(query.get('days', [''])[0],
                                                                   query.get('mode', [''])[0]))
                assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                          '/insights.js': ('insights.js', 'text/javascript; charset=utf-8'),
                          '/insights.css': ('insights.css', 'text/css; charset=utf-8'),
                          '/parking.js': ('parking.js', 'text/javascript; charset=utf-8'),
                          '/usage-reports.js': ('usage-reports.js', 'text/javascript; charset=utf-8'),
                          '/charge-ledger.js': ('charge-ledger.js', 'text/javascript; charset=utf-8'),
                          '/custom-reminders.js': ('custom-reminders.js', 'text/javascript; charset=utf-8'),
                          '/trip-tags.js': ('trip-tags.js', 'text/javascript; charset=utf-8'),
                          '/charge-comparison.js': ('charge-comparison.js', 'text/javascript; charset=utf-8'),
                          '/parameter-experiments.js': ('parameter-experiments.js', 'text/javascript; charset=utf-8'),
                          '/usage-calendar.js': ('usage-calendar.js', 'text/javascript; charset=utf-8'),
                          '/vehicle-life.js': ('vehicle-life.js', 'text/javascript; charset=utf-8'),
                          '/data-quality.js': ('data-quality.js', 'text/javascript; charset=utf-8'),
                          '/trip-card-renderer.js': ('trip-card-renderer.js', 'text/javascript; charset=utf-8'),
                          '/trip-cards.js': ('trip-cards.js', 'text/javascript; charset=utf-8'),
                          '/vehicle.js': ('vehicle.js', 'text/javascript; charset=utf-8'),
                          '/vehicle.css': ('vehicle.css', 'text/css; charset=utf-8'),
                          '/route-quality.js': ('route-quality.js', 'text/javascript; charset=utf-8'),
                          '/history.js': ('history.js', 'text/javascript; charset=utf-8'),
                          '/trips.js': ('trips.js', 'text/javascript; charset=utf-8'),
                          '/trip-management.js': ('trip-management.js', 'text/javascript; charset=utf-8'),
                          '/trips.css': ('trips.css', 'text/css; charset=utf-8'),
                          '/field-reviews.js': ('field-reviews.js', 'text/javascript; charset=utf-8'),
                          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                          '/storage-management.js': ('storage-management.js', 'text/javascript; charset=utf-8'),
                          '/storage-management.css': ('storage-management.css', 'text/css; charset=utf-8'),
                          '/app.css': ('app.css', 'text/css; charset=utf-8'),
                          '/vendor/leaflet.js': ('vendor/leaflet.js', 'text/javascript; charset=utf-8'),
                          '/vendor/leaflet.css': ('vendor/leaflet.css', 'text/css; charset=utf-8'),
                          '/car.svg': ('car.svg', 'image/svg+xml'),
                          '/car-001.png': ('car-001.png', 'image/png')}
                if url.path in assets:
                    name, content_type = assets[url.path]
                    return self.send(200, (STATIC / name).read_bytes(), content_type)
                return self.send(404, {'error': '页面不存在。'})
            except ValueError:
                self.send(400, {'error': '日期或参数无效。'})
            except Exception:
                self.send(500, {'error': '本地数据暂时无法读取。'})

        def do_POST(self):
            if auth and self.path in ('/auth/login', '/auth/logout'):
                return self.auth_post()
            if not self.signed_in():
                return self.send(401, {'error': '请先登录。'})
            if not self.permitted(mutation=True):
                return self.send(403, {'error': '请求校验失败，请从本机页面操作。'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                limit = 32768 if self.path == '/api/field-reviews' else 16384 if self.path.startswith(('/api/insights/','/api/trips/manage/')) else 4096
                if not 0 < length <= limit or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('请求格式无效。')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('请求必须为 JSON 对象。')
                if self.path == '/api/refresh':
                    return self.send(200, app.refresh(data.get('vehicle', 1)))
                if self.path in ('/api/trips/manage/preview','/api/trips/manage/execute'):
                    owner = hashlib.sha256(self.token().encode()).hexdigest()
                    return self.send(200, app.manage_trips(self.path.rsplit('/',1)[1], data, owner))
                if self.path == '/api/insights/ledger':
                    return self.send(200, app.update_insight_record('ledger',data))
                if self.path == '/api/insights/rules':
                    return self.send(200, app.update_insight_record('rules',data))
                if self.path == '/api/insights/rules/preview':
                    return self.send(200, app.update_insight_record('rule-preview',data))
                if self.path == '/api/insights/trip-tags':
                    return self.send(200, app.update_insight_record('trip-tags',data))
                if self.path == '/api/insights/experiments':
                    return self.send(200, app.update_insight_record('experiments',data))
                if self.path == '/api/insights/life':
                    return self.send(200, app.update_insight_record('life',data))
                if self.path == '/api/storage/preview':
                    owner = hashlib.sha256(self.token().encode()).hexdigest()
                    return self.send(200, app.storage_manager.preview(data.get('action'), data.get('target'), owner))
                if self.path == '/api/storage/execute':
                    owner = hashlib.sha256(self.token().encode()).hexdigest()
                    return self.send(200, app.storage_manager.execute(data.get('token'), data.get('confirmation'), owner))
                if self.path == '/api/field-reviews':
                    return self.send(200, app.review_field(data))
                if self.path == '/api/recording':
                    return self.send(200, app.recording(data.get('active'), data.get('interval', 60)))
                return self.send(404, {'error': '操作不存在。'})
            except ValueError as exc:
                self.send(400, {'error': str(exc)[:150]})
            except ApiError as exc:
                self.send(502, {'error': str(exc)})
            except Exception:
                with app.lock:
                    app.error = '本地服务或存储发生错误，请检查后重试。'
                self.send(500, {'error': app.error})

    class LocalHTTPServer(ThreadingHTTPServer):
        # A page now loads many same-origin assets. Queue connection bursts while
        # the accept loop yields to handlers, rather than resetting asset sockets.
        request_queue_size = 128

    server = LocalHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.timeout = 15
    return server


def serve(port=8765):
    app = App()
    try:
        auth_path = os.environ.get('ZEEKR_AUTH_FILE')
        auth = None
        if auth_path:
            from .storage import load
            auth = WebAuth(load(auth_path))
        server = make_server(app, port, auth=auth, public_origin=os.environ.get('ZEEKR_PUBLIC_ORIGIN'))
        app.start_monitor()
        print('Zeekr Web：http://127.0.0.1:%d（仅本机；统一采集默认开启；Ctrl+C 退出）' % server.server_port, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\nWeb 服务已停止。')
        finally:
            server.server_close()
    finally:
        app.close()
    return 0
