"""Outbound-only WeCom notifications; secrets never appear in errors."""
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


class WeComSender:
    def __init__(self, config_path):
        self.config_path = config_path

    def __call__(self, message):
        try:
            url = load(self.config_path).get('webhook_url', '')
        except Exception:
            raise DeliveryError('通知配置无法读取', permanent=True) from None
        if not re.fullmatch(r'https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]{16,128}', url):
            raise DeliveryError('通知地址无效', permanent=True)
        payload = json.dumps({'msgtype': 'text', 'text': {'content': message}}, ensure_ascii=False).encode()
        if len(message.encode('utf-8')) > 2048:
            raise DeliveryError('通知内容过长', permanent=True)
        request = Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
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
