"""Local display profiles, separate from gateway status and credentials."""
import json
import math
import os
from pathlib import Path
import stat

DEFAULT_PATH = Path(__file__).with_name('vehicle_profiles.json')
MAX_PROFILE_BYTES = 1024*1024


def _display_text(value):
    if not isinstance(value,str) or len(value)>120:return False
    try:value.encode('utf-8')
    except UnicodeEncodeError:return False
    return True


def vehicle_profile(key, number, count, path=DEFAULT_PATH):
    fallback = {'name': '车辆 %d' % number, 'variant': '车辆资料待配置', 'image': '', 'image_alt': ''}
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size>MAX_PROFILE_BYTES:return fallback
            with os.fdopen(fd,'rb',closefd=False) as stream:payload=stream.read(MAX_PROFILE_BYTES+1)
            if len(payload)>MAX_PROFILE_BYTES:return fallback
        finally:os.close(fd)
        config = json.loads(payload.decode('utf-8'))
        profiles = config.get('vehicles', {})
        profile = profiles.get(key)
        if profile is None and count == 1:
            profile = config.get('single_vehicle')
        if not isinstance(profile, dict):
            return fallback
        for field in fallback:
            value = profile.get(field)
            if _display_text(value):
                fallback[field] = value
        # Reference artwork is local only, never load a URL from a profile.
        if fallback['image'] not in ('', '/car.svg'):
            fallback['image'] = ''
        capacity = profile.get('battery_capacity_kwh')
        if type(capacity) in (int, float) and 0 < capacity <= 1000 and math.isfinite(capacity):
            fallback['battery_capacity_kwh'] = capacity
        rated = profile.get('range_km')
        standard = profile.get('range_standard')
        if (type(rated) in (int, float) and 0 < rated <= 3000 and math.isfinite(rated)
                and standard in ('CLTC', 'WLTP', 'NEDC', 'EPA')):
            fallback['range_km'] = rated
            fallback['range_standard'] = standard
            source = profile.get('range_source')
            if _display_text(source):
                fallback['range_source'] = source
        return fallback
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return fallback
