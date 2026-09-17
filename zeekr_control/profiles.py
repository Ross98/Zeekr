"""Local display profiles, separate from gateway status and credentials."""
import json
import math
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name('vehicle_profiles.json')


def vehicle_profile(key, number, count, path=DEFAULT_PATH):
    fallback = {'name': '车辆 %d' % number, 'variant': '车辆资料待配置', 'image': '', 'image_alt': ''}
    try:
        config = json.loads(Path(path).read_text(encoding='utf-8'))
        profiles = config.get('vehicles', {})
        profile = profiles.get(key)
        if profile is None and count == 1:
            profile = config.get('single_vehicle')
        if not isinstance(profile, dict):
            return fallback
        for field in fallback:
            value = profile.get(field)
            if isinstance(value, str) and len(value) <= 120:
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
            if isinstance(source, str) and len(source) <= 120:
                fallback['range_source'] = source
        return fallback
    except (OSError, ValueError, TypeError, AttributeError):
        return fallback
