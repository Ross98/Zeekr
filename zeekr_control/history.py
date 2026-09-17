"""Read-only GW3 history adapter. Domestic account compatibility needs live verification.

Only imported GW3 credentials are used; no automatic login, vehicle control,
route fallback, or retry. Protocol references are recorded in docs/api-notes.md.
"""
import base64
from datetime import datetime, timedelta
import hashlib
import hmac
import json
import re
import time
import uuid
from zoneinfo import ZoneInfo

from .client import transport as gateway_transport
from .errors import ApiError, RateLimited
from .query_policy import QueryPolicy
from .summary import number as decimal_number, updated_at

HOST = 'https://snc-tsp-api.zeekrlife.com'
PATHS = {'history': ('POST', '/ms-vehicle-trail/api/v1.0/journalLog/trip/listForPage'),
         'history_points': ('GET', '/ms-vehicle-trail/api/v1.0/journalLog/trackpoint/list')}
# App signing constant from RexzeLu/zeekr_ha (MIT); not an owner's credential.
SIGNING_SECRET = '890efe3207af95348b95f66b2ee7da04'
PAGE_SIZE = 20
MAX_POINTS = 5000


class HistoryError(ApiError):
    def __init__(self, status, message, retry_after=None):
        self.status = status
        super().__init__(message, retry_after=retry_after)

    def result(self):
        result = {'status': self.status, 'message': str(self), 'source': '云端历史'}
        if self.retry_after is not None:
            result['retry_after'] = self.retry_after
        return result


def day_window(date):
    if not isinstance(date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
        raise ValueError('日期格式应为 YYYY-MM-DD。')
    try:
        start = datetime.strptime(date, '%Y-%m-%d').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        end = start + timedelta(days=1)
        return int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    except (OverflowError, OSError) as exc:
        raise ValueError('日期超出支持范围。') from exc


def integer(value, minimum=0, maximum=32503680000000):
    # Preserve 64-bit trip identifiers without a float round-trip.
    if type(value) is int:
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r'[0-9]{1,20}', value):
        parsed = int(value)
    else:
        raise ValueError('参数须为有效整数。')
    if not minimum <= parsed <= maximum:
        raise ValueError('参数超出范围。')
    return parsed


def validate_session(session):
    fields = ('historyAccessToken', 'historyDeviceId', 'historyVin', 'historyVehicleKey')
    if not all(isinstance(session.get(key), str) and session[key].strip() for key in fields):
        raise HistoryError('authorization_required', '需要连接云端历史账号；现有车辆状态会话不能用于历史查询。')
    if any(len(session[key]) > 8192 or any(ord(c) < 32 or ord(c) > 126 for c in session[key]) for key in fields):
        raise HistoryError('authorization_required', '云端历史凭据格式无效，请在本机重新导入。')
    try:
        encrypted = base64.b64decode(session['historyVin'], validate=True)
    except (ValueError, base64.binascii.Error):
        encrypted = b''
    if len(encrypted) != 32 or not re.fullmatch(r'[0-9a-f]{64}', session['historyVehicleKey']):
        raise HistoryError('authorization_required', '云端历史车辆凭据格式无效，请使用该车辆对应的 X-VIN。')


def connection_status(session, vehicle_key=None):
    try:
        validate_session(session)
        if vehicle_key and session['historyVehicleKey'] != vehicle_key:
            raise HistoryError('vehicle_mismatch', '历史凭据对应其他车辆，请为当前车辆重新连接。')
        return {'status': 'ready', 'message': '可查询云端历史',
                'connection_id': hashlib.sha256(json.dumps(session, sort_keys=True).encode()).hexdigest(),
                'detail': '已配置历史会话；账号权限与国内接口兼容性以查询结果为准。'}
    except HistoryError as exc:
        return exc.result()


def schema_error():
    return HistoryError('protocol_error', '历史服务返回了无法识别的数据；未将其当作没有行程。')


def number(value, minimum, maximum):
    parsed = decimal_number(value, minimum, maximum)
    return float(parsed) if parsed is not None else None


def trip_summary(raw):
    if not isinstance(raw, dict):
        raise schema_error()
    try:
        identity = str(integer(raw.get('tripId'), maximum=2**63 - 1))
        report_time = integer(raw.get('reportTime'), minimum=1)
    except ValueError:
        raise schema_error() from None
    start = number(raw.get('startTime'), 1, 32503680000000)
    end = number(raw.get('endTime'), 1, 32503680000000)
    distance = number(raw.get('traveledDistance', raw.get('distance')), 0, 100000)
    duration = (end - start) / 60000 if start is not None and end is not None and end >= start else None
    return {'id': identity, 'report_time': report_time, 'report_at': updated_at(report_time),
            'start_time': start, 'end_time': end, 'start_at': updated_at(start), 'end_at': updated_at(end),
            'duration_minutes': duration, 'distance_km': distance,
            'average_speed_kmh': number(raw.get('avgSpeed'), 0, 500)}


def normalize_points(data):
    if isinstance(data, list):
        rows, system = data, None
    elif isinstance(data, dict) and isinstance(data.get('trackPoints'), list):
        rows, system = data['trackPoints'], data.get('coordinateSystem')
    else:
        raise schema_error()
    points, segments, current = [], [], []
    for raw in rows[:MAX_POINTS]:
        if not isinstance(raw, dict):
            raise schema_error()
        lat, lon = number(raw.get('latitude'), -90, 90), number(raw.get('longitude'), -180, 180)
        coordinate_system = raw.get('coordinateSystem', system)
        # The legacy status coordinate scaling and marsCoordinates flag do not
        # establish the format of a different service's history points.
        plottable = lat is not None and lon is not None and (lat != 0 or lon != 0) and coordinate_system == 'WGS84'
        timestamp = number(raw.get('reportTime'), 1, 32503680000000)
        point = {'latitude': lat, 'longitude': lon, 'plottable': plottable,
                 'coordinate_system': 'WGS84' if coordinate_system == 'WGS84' else '未确认',
                 'time': timestamp, 'time_label': updated_at(timestamp), 'time_source': '轨迹点上报时间',
                 'trusted': plottable and raw.get('posCanBeTrusted') is not False}
        points.append(point)
        previous = current[-1] if current else None
        continuous = (previous and timestamp is not None and previous['time'] is not None
                      and 0 < timestamp - previous['time'] <= 300000)
        if not point['trusted'] or not continuous:
            if current:
                segments.append(current)
            current = []
        if point['trusted']:
            current.append(point)
    if current:
        segments.append(current)
    return {'status': 'available' if rows else 'empty', 'source': '云端历史',
            'points': points, 'segments': segments, 'count': len(points), 'truncated': len(rows) > MAX_POINTS,
            'unplottable_count': sum(not point['plottable'] for point in points)}


class HistoryClient:
    def __init__(self, session, transport=gateway_transport, query_policy=None):
        self.session = dict(session)
        self.transport = transport
        self.policy = query_policy if query_policy is not None else (QueryPolicy() if transport is gateway_transport else None)
        self.cached = False
        self.fetched_at = None

    def _headers(self, method, path, query, body):
        token = self.session['historyAccessToken']
        headers = {'X-APP-ID': 'ZEEKRCNCH001M0001', 'AppId': 'ONEX97FB91F061405',
                   'X-TIMESTAMP': str(int(time.time() * 1000)), 'X-API-SIGNATURE-VERSION': '2.0',
                   'Accept-Language': 'en-US', 'Content-Type': 'application/json; charset=UTF-8',
                   'X-PROJECT-ID': 'ZEEKR', 'X-P': 'Android', 'X-DEVICE-ID': self.session['historyDeviceId'],
                   'X-APP-OS-VERSION': '5.0.5', 'X-PLATFORM': 'APP',
                   'X-API-SIGNATURE-NONCE': str(uuid.uuid4()), 'User-Agent': 'okhttp/4.12.0',
                   'Authorization': token if token.startswith('Bearer ') else 'Bearer ' + token,
                   'X-VIN': self.session['historyVin']}
        signed = {'x-app-id', 'content-type', 'x-api-signature-nonce', 'x-timestamp',
                  'x-api-signature-version', 'x-project-id', 'authorization', 'accept-language',
                  'x-vin', 'x-device-id', 'x-platform'}
        canonical = ''.join(key.lower() + ':' + headers[key] + '\n'
                            for key in sorted(headers, key=str.lower) if key.lower() in signed)
        if query:
            canonical += query + '\n'
        if body is not None:
            canonical += base64.b64encode(hashlib.md5(body).digest()).decode() + '\n'
        canonical += method + '\n' + path
        headers['X-SIGNATURE'] = base64.b64encode(hmac.new(SIGNING_SECRET.encode(), canonical.encode(), hashlib.sha256).digest()).decode()
        return headers

    def _request(self, operation, params=None, payload=None):
        validate_session(self.session)
        method, path = PATHS[operation]
        # Every query value is a validated integer, never an arbitrary URL.
        query = '&'.join('%s=%s' % item for item in sorted((params or {}).items()))
        body = None if payload is None else json.dumps(payload, separators=(',', ':')).encode()

        def fetch():
            result = self.transport(method, HOST + path + ('?' + query if query else ''),
                                    self._headers(method, path, query, body), body)
            if not isinstance(result, dict):
                raise schema_error()
            code = str(result.get('code', ''))
            if code != '000000' or result.get('success') is False:
                if code == '079001' or code == '403':
                    raise HistoryError('forbidden', '账号无权读取云端历史；请在官方 App 核对车辆分享权限。')
                if code in ('079021', '401', '40101', '40102', '40106', '40001', '10401'):
                    raise HistoryError('session_expired', '云端历史会话已失效或被替换，请重新连接历史账号。')
                if code == '079025':
                    raise HistoryError('protocol_error', '历史服务签名校验失败，需要核对当前 App 协议。')
                safe_code = code if re.fullmatch('[0-9]{1,12}', code) else 'unknown'
                raise HistoryError('request_failed', '云端历史查询失败，网关代码 %s；未自动重试。' % safe_code)
            return result.get('data')

        try:
            if self.policy is None:
                result = fetch()
                self.fetched_at = time.time()
                return result
            resource = json.dumps([self.session['historyVehicleKey'], self.session['historyVin'],
                                   self.session['historyDeviceId'], params, payload], sort_keys=True)
            result = self.policy.run(self.session.get('userId', 'history'), self.session['historyAccessToken'], operation, resource, fetch)
            self.cached, self.fetched_at = self.policy.cache_hit, self.policy.fetched_at
            return result
        except HistoryError:
            raise
        except RateLimited as exc:
            raise HistoryError('rate_limited', str(exc), exc.seconds) from None
        except ApiError as exc:
            if exc.retry_after is not None:
                raise HistoryError('rate_limited', str(exc), exc.retry_after) from None
            http_status = getattr(exc, 'http_status', None)
            if http_status == 401:
                raise HistoryError('session_expired', '云端历史会话失效，请重新连接历史账号。') from None
            if http_status == 403:
                raise HistoryError('forbidden', '历史服务拒绝访问，请核对账号权限。') from None
            raise HistoryError('request_failed', str(exc)) from None

    def day(self, date, cursor=None):
        lower, upper = day_window(date)
        end = upper - 1 if cursor is None else integer(cursor, lower, upper - 1)
        data = self._request('history', payload={'startTime': lower, 'endTime': end,
            'pageSize': PAGE_SIZE, 'currentPage': 1, 'lastId': -1})
        if not isinstance(data, dict):
            raise schema_error()
        rows = data.get('data', data.get('list'))
        if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
            raise schema_error()
        try:
            total = integer(data['total']) if 'total' in data else None
        except ValueError:
            raise schema_error() from None
        if total is not None and total < len(rows) or not rows and total not in (None, 0):
            raise schema_error()
        trips = [trip_summary(row) for row in rows]
        # reportTime is the pagination/date key; an overnight trip can start on
        # the preceding date and must not be silently discarded.
        if any(not lower <= trip['report_time'] <= end for trip in trips):
            raise schema_error()
        next_cursor = None
        if len(rows) == PAGE_SIZE or total is not None and total > len(rows):
            try:
                boundary = integer(data.get('lastId'), lower, end)
            except ValueError:
                raise schema_error() from None
            if boundary > min(trip['report_time'] for trip in trips):
                raise schema_error()
            if boundary > lower:
                next_cursor = boundary - 1
        return {'status': 'available' if trips else 'empty', 'source': '云端历史', 'date': date,
                'trips': trips, 'next_cursor': next_cursor, 'total': total,
                'cached': self.cached, 'read_at': updated_at(self.fetched_at * 1000) if self.fetched_at else '未知'}

    def points(self, trip_id, report_time):
        identity = integer(trip_id, maximum=2**63 - 1)
        timestamp = integer(report_time, minimum=1)
        data = self._request('history_points', params={'tripId': identity, 'tripReportTime': timestamp})
        return normalize_points(data)
