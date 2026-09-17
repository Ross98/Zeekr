"""Loopback-only Web UI and explicitly enabled cached-position collection."""
import hashlib
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
from .storage import DEFAULT_PATH, load
from .summary import updated_at
from .tracks import TrackStore
from .web_model import build_model, parse_location
from .profiles import vehicle_profile

STATIC = Path(__file__).parent / 'static'
HISTORY = {'status': 'not_connected', 'message': '云端历史尚未接入',
           'detail': '已找到社区整理的行程与轨迹点路由，但请求参数、认证和本车副账号权限尚未验证。此状态不代表没有历史行程。'}


class RefreshBusy(ValueError):
    """Another refresh is already responsible for this sampling interval."""


class App:
    def __init__(self, session_path=DEFAULT_PATH, database_path=None, client_factory=Client):
        self.session_path = Path(session_path)
        self.database_path = Path(database_path or self.session_path.parent / 'tracks.sqlite3')
        self.client_factory = client_factory
        self.request_key = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.refresh_lock = threading.Lock()
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
        self.recording_status = 'never'
        self.recording_error = None
        self.error = None
        self.active = False
        self.interval = 300
        self.next_due = 0
        self.last_sample = None
        self.last_new = None
        self.store = None
        self.worker = threading.Thread(target=self._collect, name='zeekr-collector', daemon=True)
        self.worker.start()

    def state(self):
        with self.lock:
            try:
                from .monitor_runtime import read_status
                monitoring = read_status(self.session_path.parent)
            except Exception:
                monitoring = {'status': 'unavailable', 'online': False, 'events': []}
            try:
                authenticated = bool(load(self.session_path).get('accessToken'))
                session_error = None
            except ApiError as exc:
                authenticated, session_error = False, str(exc)
            try:
                archives = self._store().vehicles() if self.database_path.exists() else []
                storage_error = None
            except Exception:
                archives, storage_error = [], '本地轨迹存储暂不可用。'
            return {'request_key': self.request_key, 'authenticated': authenticated,
                    'model': self.model, 'vehicle': self.vehicle, 'vehicles': self.vehicles,
                    'read_at': updated_at(self.read_at), 'read_time': self.read_at,
                    'query_cached': self.query_cached, 'refresh_result': self.refresh_result,
                    'next_query_at': self.next_query_at, 'profile': self.profile, 'archived_vehicles': archives,
                    'error': self.error or session_error or storage_error,
                    'recording': {'active': self.active, 'interval': self.interval,
                                  'status': self.recording_status if self.recording_status != 'never' or not archives else 'paused',
                                  'error': self.recording_error,
                                  'last_sample': updated_at(self.last_sample), 'last_new': updated_at(self.last_new)},
                    'history': HISTORY, 'monitoring': monitoring,
                    'storage_bytes': self.database_path.stat().st_size if self.database_path.exists() else 0}

    def refresh(self, vehicle):
        if type(vehicle) is not int or vehicle < 1:
            raise ValueError('请选择有效车辆序号。')
        if not self.refresh_lock.acquire(blocking=False):
            raise RefreshBusy('正在读取，请稍后。')
        client = None
        try:
            with self.lock:
                if self.active and vehicle != self.vehicle:
                    raise ValueError('请先暂停采集，再切换车辆。')
            client = self.client_factory(load(self.session_path))
            vehicles = client.vehicles()
            if vehicle > len(vehicles):
                raise ValueError('车辆序号超出范围，或账号下没有可用车辆。')
            vins = find_vins(vehicles[vehicle - 1])
            if len(vins) != 1:
                raise ApiError('车辆未返回唯一有效 VIN。')
            vin = next(iter(vins))
            raw = client.status(vin)
            model = build_model(raw)
            with self.lock:
                key = hashlib.sha256(vin.encode()).hexdigest()
                previous_time = self.model.get('updated_time') if self.model and key == self.vehicle_key else None
                incoming_time = model['updated_time']
                self.vehicle, self.vehicle_key = vehicle, key
                self.profile = vehicle_profile(key, vehicle, len(vehicles))
                self.vehicles = [{'number': index, 'label': '车辆 %d' % index} for index in range(1, len(vehicles) + 1)]
                fetched_at = getattr(client, "last_query_fetched_at", None)
                self.query_cached = bool(getattr(client, 'last_query_cached', False))
                self.next_query_at = getattr(client, 'next_query_at', None)
                self.refresh_result = ('cached' if self.query_cached else 'time_unknown' if incoming_time is None
                                       else 'new' if previous_time is None or incoming_time > previous_time else 'unchanged')
                self.raw, self.model, self.read_at, self.error = raw, model, int((fetched_at if fetched_at is not None else time.time()) * 1000), None
                if self.active:
                    self._record()
                return self.state()
        except ApiError as exc:
            with self.lock:
                self.error = str(exc)
                self.next_query_at = getattr(client, 'next_query_at', self.next_query_at)
                if self.active:
                    self.recording_status, self.recording_error = 'failed', self.error
                self.active = False
            raise
        finally:
            self.refresh_lock.release()

    def _store(self):
        if self.store is None:
            self.store = TrackStore(self.database_path)
        return self.store

    def _record(self):
        observed = int(time.time() * 1000)
        if self._store().record(self.vehicle_key, self.raw, observed, self.interval * 3):
            self.last_new = observed
        self.last_sample = observed

    def recording(self, active, interval):
        if type(active) is not bool or type(interval) is not int or not 60 <= interval <= 3600:
            raise ValueError('采集开关必须为布尔值，间隔须为 60–3600 秒的整数。')
        with self.lock:
            if active and self.raw is None:
                raise ValueError('请先读取车辆，再开启采集。')
            if active and self.error:
                raise ValueError('请先手动刷新成功，再恢复采集。')
            if active and self.refresh_lock.locked():
                raise ValueError('正在读取，请稍后启用采集。')
            self.interval = interval
            if active:
                try:
                    self._record()
                except Exception:
                    self.active = False
                    self.recording_status = 'failed'
                    self.recording_error = '本地采集存储失败，请检查后重试。'
                    raise
            self.active = active
            self.recording_status = 'active' if active else 'paused'
            self.recording_error = None
            self.next_due = time.monotonic() + interval
            return self.state()

    def _collect(self):
        while not self.stop.wait(1):
            with self.lock:
                due = self.active and time.monotonic() >= self.next_due
                vehicle = self.vehicle
                if due:
                    self.next_due = time.monotonic() + self.interval
            if due:
                try:
                    self.refresh(vehicle)
                except RefreshBusy:
                    pass  # A manual refresh in progress supplies the same sample.
                except Exception as exc:
                    with self.lock:
                        self.active = False
                        self.error = str(exc) if isinstance(exc, ApiError) else '采集已暂停：本地存储或读取失败。'
                        self.recording_status, self.recording_error = 'failed', self.error

    def location(self):
        with self.lock:
            result = parse_location(self.raw or {})
            result['read_at'] = updated_at(self.read_at)
            return result

    def tracks(self, date, archive=None):
        with self.lock:
            # Validate dates even before a database or a selected vehicle exists.
            from datetime import datetime
            parsed = datetime.strptime(date, '%Y-%m-%d')
            if parsed.strftime('%Y-%m-%d') != date:
                raise ValueError('日期格式无效。')
            if not self.database_path.exists():
                return {'observations': [], 'segments': [], 'count': 0, 'date': date,
                        'source': '本地采样', 'truncated': False}
            vehicles = self._store().vehicles()
            keys = {item['key'] for item in vehicles}
            if archive and archive not in keys:
                raise ValueError('所选本地车辆不存在。')
            selected = archive or self.vehicle_key or (vehicles[0]['key'] if vehicles else '')
            return self._store().day(selected, date)

    def close(self):
        self.stop.set()
        with self.lock:
            self.active = False
        self.worker.join(timeout=1.5)


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
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if not self.permitted():
                return self.send(403, {'error': '仅允许本机同源访问。'})
            if auth and self.path in ('/login.js', '/login.css'):
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
                if url.path == '/api/location':
                    return self.send(200, app.location())
                if url.path == '/api/history':
                    return self.send(200, HISTORY)
                if url.path == '/api/tracks':
                    query = parse_qs(url.query)
                    return self.send(200, app.tracks(query.get('date', [''])[0], query.get('vehicle', [None])[0]))
                assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
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
                if not 0 < length <= 4096 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('请求格式无效。')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('请求必须为 JSON 对象。')
                if self.path == '/api/refresh':
                    return self.send(200, app.refresh(data.get('vehicle', 1)))
                if self.path == '/api/recording':
                    return self.send(200, app.recording(data.get('active'), data.get('interval', 300)))
                return self.send(404, {'error': '操作不存在。'})
            except ValueError as exc:
                self.send(400, {'error': str(exc)[:150]})
            except ApiError as exc:
                self.send(502, {'error': str(exc)})
            except Exception:
                with app.lock:
                    was_active = app.active
                    app.active = False
                    app.error = '本地服务或轨迹存储发生错误，采集已暂停。'
                    if was_active:
                        app.recording_status, app.recording_error = 'failed', app.error
                self.send(500, {'error': app.error})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
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
        print('Zeekr Web：http://127.0.0.1:%d（仅本机；采集默认关闭；Ctrl+C 退出）' % server.server_port, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\nWeb 服务已停止。')
        finally:
            server.server_close()
    finally:
        app.close()
    return 0
