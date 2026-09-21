"""Outbound-only notification senders; secrets never appear in errors."""
import base64
import hashlib
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .storage import load


class DeliveryError(Exception):
    def __init__(self, message, ambiguous=False, permanent=False):
        super().__init__(message)
        self.ambiguous = ambiguous
        self.permanent = permanent


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class BarkSender:
    def __init__(self, config_path):
        self.config_path = config_path

    def __call__(self, title, body=None):
        if body is None:
            title, body = '极氪车辆提醒', title
        try:
            config = load(self.config_path)
            base_url = config.get('base_url', '')
            device_key = config.get('device_key', '')
        except Exception:
            raise DeliveryError('Bark 配置无法读取', permanent=True) from None
        if not re.fullmatch(r'https://[A-Za-z0-9.-]+(?::\d+)?(?:/[A-Za-z0-9._~-]+)*/?', base_url):
            raise DeliveryError('Bark 服务地址无效', permanent=True)
        if not isinstance(device_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,256}', device_key):
            raise DeliveryError('Bark 设备 Key 无效', permanent=True)
        if not isinstance(title, str) or not isinstance(body, str):
            raise DeliveryError('Bark 通知内容无效', permanent=True)
        payload = {'device_key': device_key, 'title': title, 'body': body,
                   'group': 'Zeekr', 'level': 'active'}
        request = Request(base_url.rstrip('/') + '/push',
                          data=json.dumps(payload, ensure_ascii=False).encode(),
                          headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
        try:
            with build_opener(NoRedirect()).open(request, timeout=20) as response:
                result = json.loads(response.read(65536))
        except HTTPError as exc:
            raise DeliveryError('Bark HTTP 错误 %d' % exc.code, ambiguous=exc.code >= 500,
                                permanent=300 <= exc.code < 500 and exc.code != 429) from None
        except (URLError, OSError, ValueError):
            raise DeliveryError('Bark 响应未确认', ambiguous=True) from None
        if not isinstance(result, dict) or type(result.get('code')) is not int:
            raise DeliveryError('Bark 响应格式未确认', ambiguous=True)
        if result['code'] != 200:
            raise DeliveryError('Bark 推送被拒绝，代码 %d' % result['code'],
                                permanent=400 <= result['code'] < 500 and result['code'] != 429)


class FallbackSender:
    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback

    def __call__(self, message):
        try:
            self.primary(message)
        except DeliveryError as exc:
            if exc.ambiguous:
                raise
            self.fallback(message)


class WeComSender:
    def __init__(self, config_path):
        self.config_path = config_path

    def __call__(self, message):
        self._send({'msgtype': 'text', 'text': {'content': message}},
                   len(message.encode('utf-8')), 2048)

    def send_markdown(self, message):
        self._send({'msgtype': 'markdown', 'markdown': {'content': message}},
                   len(message.encode('utf-8')), 4096)

    def send_image(self, content):
        if not isinstance(content, bytes) or not content.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8')):
            raise DeliveryError('通知图片格式无效', permanent=True)
        self._send({'msgtype': 'image', 'image': {
            'base64': base64.b64encode(content).decode('ascii'),
            'md5': hashlib.md5(content).hexdigest()}}, len(content), 2 * 1024 * 1024)

    def _send(self, payload, size, limit):
        try:
            url = load(self.config_path).get('webhook_url', '')
        except Exception:
            raise DeliveryError('通知配置无法读取', permanent=True) from None
        if not re.fullmatch(r'https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]{16,128}', url):
            raise DeliveryError('通知地址无效', permanent=True)
        if size > limit:
            raise DeliveryError('通知内容过长', permanent=True)
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        request = Request(url, data=encoded, headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with build_opener(NoRedirect()).open(request, timeout=20) as response:
                result = json.loads(response.read(65536))
        except HTTPError as exc:
            # A server error may occur after the message has been accepted.
            raise DeliveryError('通知 HTTP 错误 %d' % exc.code, ambiguous=exc.code >= 500,
                                permanent=300 <= exc.code < 500 and exc.code != 429) from None
        except (URLError, OSError, ValueError):
            raise DeliveryError('通知响应未确认', ambiguous=True) from None
        if not isinstance(result, dict) or type(result.get('errcode')) is not int:
            raise DeliveryError('通知响应格式未确认', ambiguous=True)
        code = result['errcode']
        if code != 0:
            raise DeliveryError('通知被拒绝，代码 %d' % code, permanent=code not in (-1, 45009))
