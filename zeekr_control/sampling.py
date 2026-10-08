"""Shared private settings for collection and status-query protection."""
from pathlib import Path

from .errors import ApiError
from .storage import load, save

DEFAULT_INTERVAL = 30
MIN_INTERVAL = 10
MAX_INTERVAL = 60


def public_policy():
    return dict(version=1, default_interval=DEFAULT_INTERVAL, min_interval=MIN_INTERVAL,
                max_interval=MAX_INTERVAL, parking_mode='same_as_normal', backoff_enabled=True)


def validate_interval(interval):
    if type(interval) is not int or not MIN_INTERVAL <= interval <= MAX_INTERVAL:
        raise ValueError('采样间隔须为 10–60 秒的整数。')
    return interval


def read_settings(root):
    data = load(Path(root) / 'sampling.json')
    try:
        interval = validate_interval(int(data.get('interval', str(DEFAULT_INTERVAL))))
    except ValueError:
        raise ApiError('采样间隔配置无效，应为 10–60 秒的整数。') from None
    return data.get('enabled', 'true') != 'false', interval


def save_settings(root, active, interval=None):
    if type(active) is not bool:
        raise ValueError('采集开关须为布尔值。')
    if interval is None:
        _, interval = read_settings(root)
    validate_interval(interval)
    save(Path(root) / 'sampling.json', {'enabled': 'true' if active else 'false',
                                       'interval': str(interval)})
