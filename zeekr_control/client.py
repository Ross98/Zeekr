"""GW1/GW2 protocol adapted from RexzeLu/zeekr_ha; see THIRD_PARTY_NOTICES.md.

Only explicitly listed authentication and cached-data endpoints are reachable.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .errors import ApiError, RateLimited
from .query_policy import QueryPolicy, retry_seconds

GW1_SECRET = 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCz09z6e9WOcNq+nUMX8Vq1Xe2EmJxuR3XbtureDCS90dfkok'
GW2_SECRET = 'e83a60805fa54de9bdfcb0f2d6bca757'
HOSTS = {1: 'https://api-gw-toc.zeekrlife.com', 2: 'https://api.zeekrline.com'}
OPERATIONS = {
    'sms': (1, 'GET', '/zeekrlife-app-user/v1/user/pub/sms/authCode'),
    'login': (1, 'POST', '/zeekrlife-app-user/v1/user/pub/login/mobile'),
    'access_code': (1, 'GET', '/zeekrlife-mp-auth2/v1/auth/accessCodeList'),
    'line_login': (2, 'POST', '/auth/account/session/secure'),
    'vehicles': (2, 'GET', '/device-platform/user/vehicle/secure'),
    'status': (2, 'GET', '/remote-control/vehicle/status/{vin}'),
}


def timestamp():
    return str(int(time.time() * 1000))


def nonce():
    return uuid.uuid4().hex.upper()


def required(data, key):
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip() or '\r' in value or '\n' in value:
        raise ApiError('响应或会话缺少有效字段：' + key)
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApiError('网关重定向已拒绝，凭据未转发。')


def transport(method, url, headers, body):
    try:
        request = Request(url, data=body, headers=headers, method=method)
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ApiError('网关响应过大。')
        return json.loads(raw)
    except HTTPError as exc:
        if exc.code == 429:
            raise RateLimited(retry_seconds(exc.headers.get('Retry-After') if exc.headers else None)) from None
        raise ApiError('网关 HTTP %d；未自动重试。' % exc.code, http_status=exc.code) from None
    except (URLError, TimeoutError, OSError):
        raise ApiError('网络或 TLS 连接失败；未自动重试。') from None
    except (ValueError, UnicodeError):
        raise ApiError('网关响应不是有效 JSON。') from None


class Client:
    def __init__(self, session=None, transport=transport, query_policy=None):
        self.session = dict(session or {})
        self.session.setdefault('deviceId', uuid.uuid4().hex)
        self.transport = transport
        self.query_policy = query_policy if query_policy is not None else (QueryPolicy() if transport is globals()["transport"] else None)
        self.last_query_cached = False
        self.last_query_fetched_at = None
        self.next_query_at = None

    def _headers(self, gateway, method, path, params, body):
        ts = timestamp()
        device = required(self.session, 'deviceId')
        if gateway == 1:
            random_value = str(secrets.randbelow(900000000) + 100000000)
            signature = hashlib.sha1(''.join(sorted([ts, random_value, GW1_SECRET])).encode()).hexdigest()
            return {
                'User-Agent': 'okhttp/4.12.0', 'request-original': 'zeekr-app',
                'Content-Type': 'application/json; charset=UTF-8',
                'app_code': 'toc_android_zeekrapp', 'app_type': 'android',
                'app_version': '5.0.5', 'platform': 'ANDROID',
                'phone_model': 'Android SDK built for arm64', 'phone_version': '26',
                'workspaceId': 'prod', 'x_gray_code': '',
                'x_ca_secret': GW1_SECRET, 'x_ca_key': 'APP-SIGN-SECRET-KEY',
                'x_ca_timestamp': ts, 'x_ca_nonce': random_value, 'x_ca_sign': signature,
                'device_id': device, 'Authorization': self.session.get('jwtToken', ''),
                'Accept-Language': 'zh-Hans-CN;q=1, en-CN;q=0.9',
            }
        random_value = nonce()
        digest = base64.b64encode(hashlib.md5(body or b'').digest()).decode()
        query = '&'.join('%s=%s' % item for item in sorted(params.items()))
        canonical = '\n'.join([
            'application/json;responseformat=3',
            'x-api-signature-nonce:' + random_value, 'x-api-signature-version:1.0',
            '', query, digest, ts, method, path,
        ])
        signature = base64.b64encode(hmac.new(GW2_SECRET.encode(), canonical.encode(), hashlib.sha1).digest()).decode()
        return {
            'content-type': 'application/json', 'x-api-signature-version': '1.0',
            'x-app-id': 'ZEEKRAPP',
            'user-agent': 'ZeekrLife/4.0.2 (iPhone; iOS 17.4.1; Scale/3.00)',
            'x-device-model': 'iPhone', 'x-device-manufacture': 'Apple',
            'x-agent-type': 'iOS', 'x-device-type': 'mobile', 'platform': 'NON-CMA',
            'x-env-type': 'production', 'accept-language': 'zh-Hans-CN;q=1, en-CN;q=0.9',
            'x-agent-version': '17.4.1', 'accept': 'application/json;responseformat=3',
            'x-device-brand': 'Apple', 'x-operator-code': 'ZEEKR',
            'x-device-identifier': device, 'authorization': self.session.get('accessToken', ''),
            'x-client-id': self.session.get('clientId', ''), 'x-timestamp': ts,
            'x-api-signature-nonce': random_value, 'x-signature': signature,
        }

    def _request(self, operation, params=None, payload=None, vin=None):
        if operation not in OPERATIONS:
            raise ApiError('不支持此操作。')
        gateway, method, path = OPERATIONS[operation]
        if operation == 'status':
            if not isinstance(vin, str) or not re.fullmatch('[A-HJ-NPR-Z0-9]{17}', vin):
                raise ApiError('VIN 必须为 17 位有效字符。')
            path = path.format(vin=vin)
        params = dict(params or {})
        if operation == 'line_login':
            params = {'identity_type': 'zeekr'}
        body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
        def fetch():
            headers = self._headers(gateway, method, path, params, body)
            # GW2's reference canonical form signs the pre-escaped target value.
            # Values are constructed internally, never passed through from a URL.
            if gateway == 2:
                query = '&'.join(quote(str(k), safe='') + '=' + quote(str(v), safe='%') for k, v in params.items())
            else:
                query = urlencode(params)
            url = HOSTS[gateway] + path + ('?' + query if query else '')
            result = self.transport(method, url, headers, body)
            if not isinstance(result, dict):
                raise ApiError('网关响应结构不符。')
            code = str(result.get('code', 'missing'))
            if code not in ('000000', '1000'):
                safe_code = code if re.fullmatch('[0-9]{1,12}', code) else 'unknown'
                raise ApiError('%s 失败，网关代码 %s；会话过期或被替换时请重新登录。' % (operation, safe_code))
            return result.get('data')

        if self.query_policy is None:
            return fetch()
        account = self.session.get('userId') or 'login'
        session = self.session.get('accessToken') or self.session.get('jwtToken') or ''
        try:
            return self.query_policy.run(account, session, operation, vin or '', fetch)
        finally:
            self.last_query_cached = self.query_policy.cache_hit
            self.last_query_fetched_at = self.query_policy.fetched_at
            self.next_query_at = self.query_policy.next_query_at

    @staticmethod
    def _phone(phone):
        if not re.fullmatch('1[0-9]{10}', phone):
            raise ApiError('请输入中国大陆 11 位手机号。')

    def send_sms(self, phone):
        self._phone(phone)
        return self._request('sms', {'mobile': phone, 'x_ca_time': timestamp(), 'regionCode': '+86'})

    def login_sms(self, phone, code):
        self._phone(phone)
        if not re.fullmatch('[0-9]{4,8}', code):
            raise ApiError('验证码格式错误。')
        data = self._request('login', payload={
            'mobile': phone, 'deviceId': self.session['deviceId'], 'smsCode': code,
            'channel': 2, 'x_ca_time': timestamp(),
            'deviceName': 'Android SDK built for arm64', 'skipSmsCode': '0',
            'regionCode': '+86', 'ip': '192.168.1.1',
        })
        self.login_jwt(required(data, 'jwtToken'))

    def login_jwt(self, token):
        required({'jwtToken': token}, 'jwtToken')
        self.session = {'deviceId': self.session['deviceId'], 'jwtToken': token}
        data = self._request('access_code', {'envType': 3})
        code = required(data, 'YIKAT_NEW')
        data = self._request('line_login', payload={'authCode': code})
        fields = {key: required(data, key) for key in ('accessToken', 'userId', 'clientId')}
        # Persist only the GW2 session needed for read requests.
        self.session = {'deviceId': self.session['deviceId'], **fields}

    def _authenticated(self):
        for key in ('accessToken', 'userId'):
            if not self.session.get(key):
                raise ApiError('尚未登录；请先运行 python3 -m zeekr_control login。')
            required(self.session, key)

    def vehicles(self):
        self._authenticated()
        data = self._request('vehicles', {'id': self.session['userId'], 'needSharedCar': 1})
        vehicles = data.get('list') if isinstance(data, dict) else None
        if not isinstance(vehicles, list) or any(not isinstance(v, dict) for v in vehicles):
            raise ApiError('车辆列表响应结构不符，不能视作无车辆。')
        return vehicles

    def status(self, vin):
        self._authenticated()
        data = self._request('status', {'latest': 'Local', 'target': 'basic%2Cmore',
                                     'userId': self.session['userId']}, vin=vin)
        if not isinstance(data, dict) or not data:
            raise ApiError('未返回有效车辆状态。')
        result = data.get('vehicleStatus', data)
        if not isinstance(result, dict) or not result:
            raise ApiError('未返回有效车辆状态。')
        return result
