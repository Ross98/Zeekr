"""Bounded, memory-only SMS challenges for reconnecting the vehicle account."""
import hashlib
import re
import secrets
import threading
import time

from .cli import find_vins
from .errors import ApiError
from .storage import load, save


class VehicleLogin:
    def __init__(self, path, client_factory, session_lock, clock=time.monotonic):
        self.path = path
        self.client_factory = client_factory
        self.session_lock = session_lock
        self.clock = clock
        self.lock = threading.Lock()
        self.sent = []
        self.attempts = []
        self.pending = None

    @staticmethod
    def error(status, text):
        return status, {'error': text}

    def send(self, data, owner):
        phone = data.get('phone')
        if not isinstance(phone, str) or not re.fullmatch(r'1[3-9][0-9]{9}', phone):
            return self.error(400, '请输入有效的中国大陆手机号。')
        if not self.lock.acquire(blocking=False):
            return self.error(409, '登录请求处理中，请稍候。')
        try:
            now = self.clock()
            if self.pending and now >= self.pending['expires']:
                self.pending = None
            self.sent = [stamp for stamp in self.sent if now - stamp < 900]
            if self.sent and (now - self.sent[-1] < 60 or len(self.sent) >= 5):
                return self.error(429, '短信发送过于频繁，请稍后重试。')
            with self.session_lock:
                baseline = load(self.path)
            self.sent.append(now)
            client = self.client_factory({})
            try:
                client.send_sms(phone)
            except Exception:
                return self.error(502, '短信发送失败，请稍后重试。')
            challenge = secrets.token_urlsafe(32)
            self.pending = dict(challenge=challenge, owner=owner, phone=phone,
                                client=client, baseline=baseline, expires=self.clock() + 600, tries=0)
            return 200, {'challenge': challenge, 'retry_after': 60, 'expires_in': 600}
        except (ApiError, OSError):
            return self.error(500, '会话文件无法安全读取，请检查服务配置。')
        finally:
            self.lock.release()

    def verify(self, data, owner):
        challenge, code = data.get('challenge'), data.get('code')
        if (not isinstance(challenge, str) or not challenge.isascii() or
                not isinstance(code, str) or not re.fullmatch(r'[0-9]{4,8}', code)):
            return self.error(400, '请输入有效的短信验证码。')
        if not self.lock.acquire(blocking=False):
            return self.error(409, '登录请求处理中，请稍候。')
        try:
            pending, now = self.pending, self.clock()
            if pending and now >= pending['expires']:
                self.pending = pending = None
            if not pending or pending['owner'] != owner or not secrets.compare_digest(pending['challenge'], challenge):
                return self.error(400, '验证请求已失效，请重新获取验证码。')
            self.attempts = [stamp for stamp in self.attempts if now - stamp < 900]
            if pending['tries'] >= 5 or len(self.attempts) >= 15:
                return self.error(429, '验证次数过多，请稍后重新获取验证码。')
            pending['tries'] += 1
            self.attempts.append(now)
            client = pending['client']
            try:
                client.login_sms(pending['phone'], code)
                vehicles = client.vehicles()
            except Exception:
                return self.error(502, '登录或车辆验证失败，请检查验证码及车辆分享权限后重试。')
            session = client.session
            old_user = pending['baseline'].get('userId')
            if not session.get('accessToken') or not session.get('userId'):
                return self.error(502, '车辆认证未完成，请重试。')
            if old_user and session['userId'] != old_user:
                return self.error(409, '账号与原采集账号不同，请使用原副账号重连。')
            vins = find_vins(vehicles)
            if not vins:
                return self.error(409, '账号下没有有效车辆，请检查车辆分享权限。')
            with self.session_lock:
                if load(self.path) != pending['baseline']:
                    self.pending = None
                    return self.error(409, '会话已在其他位置更新，请刷新后重试。')
                binding = load(self.path.parent / 'monitor-binding.json').get('vehicle_key')
                if binding and binding not in {hashlib.sha256(vin.encode()).hexdigest() for vin in vins}:
                    return self.error(409, '原绑定车辆不在当前账号下，未替换原会话。')
                save(self.path, session)
            self.pending = None
            return 200, {'connected': True}
        except (ApiError, OSError):
            return self.error(500, '会话保存失败，请检查服务存储后重试。')
        finally:
            self.lock.release()
