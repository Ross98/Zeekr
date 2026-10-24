"""Shared private settings for collection and status-query protection."""
from pathlib import Path
from contextlib import contextmanager, ExitStack
import time

from .errors import ApiError, RequestDeferred
from .storage import load, save
from .delivery_state import delivery_lock, DeliveryBusy

DEFAULT_INTERVAL = 30
MIN_INTERVAL = 10
MAX_INTERVAL = 60


class SamplingUnavailable(RequestDeferred):
    """Invalid collection controls prevented a new gateway request."""


class SamplingBusy(ApiError):
    """Another process owns the short settings read-modify-write section."""


@contextmanager
def _settings_lock(root):
    with ExitStack() as stack:
        for attempt in range(100):
            try:stack.enter_context(delivery_lock(Path(root)/'sampling-settings.lock'))
            except DeliveryBusy:
                if attempt==99:
                    raise SamplingBusy('采集设置正在保存，请稍后重试。',http_status=503,retry_after=1) from None
                time.sleep(.01)
            else:break
        yield


def read_request_settings(root):
    """Classify control failures at the pre-transport boundary, not as auth."""
    try:
        return read_settings(root)
    except ApiError:
        raise SamplingUnavailable('采集配置暂不可读或无效，未发送网络请求。',retry_after=1) from None


def public_policy():
    return dict(version=1, default_interval=DEFAULT_INTERVAL, min_interval=MIN_INTERVAL,
                max_interval=MAX_INTERVAL, parking_mode='same_as_normal', backoff_enabled=True)


def validate_interval(interval):
    if type(interval) is not int or not MIN_INTERVAL <= interval <= MAX_INTERVAL:
        raise ValueError('采样间隔须为 10–60 秒的整数。')
    return interval


def read_settings(root):
    data = load(Path(root) / 'sampling.json')
    enabled = data.get('enabled', 'true')
    if enabled not in ('true', 'false'):
        raise ApiError('采集开关配置无效，应为 true 或 false。')
    try:
        interval = validate_interval(int(data.get('interval', str(DEFAULT_INTERVAL))))
    except ValueError:
        raise ApiError('采样间隔配置无效，应为 10–60 秒的整数。') from None
    return enabled == 'true', interval


def save_settings(root, active, interval=None):
    if type(active) is not bool:
        raise ValueError('采集开关须为布尔值。')
    if interval is not None:validate_interval(interval)
    _save_settings(root,active,interval)


def save_interval(root, interval):
    validate_interval(interval)
    _save_settings(root,None,interval)


def _save_settings(root, active, interval):
    with _settings_lock(root):
        if active is None or interval is None:
            previous_active,previous_interval=read_settings(root)
            if active is None:active=previous_active
            if interval is None:interval=previous_interval
        save(Path(root) / 'sampling.json', {'enabled': 'true' if active else 'false',
                                           'interval': str(interval)})
