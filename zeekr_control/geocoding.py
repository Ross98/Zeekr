"""Optional Chinese addresses via Amap; failures must not suppress notifications."""
import json
import math
import re
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .notifications import NoRedirect
from .storage import load


def is_trusted_location(location):
    """Require usable coordinates as well as the vehicle's trust flag."""
    if (not isinstance(location, dict) or location.get('valid') is not True
            or location.get('trusted') is not True
            or location.get('coordinate_system') not in ('WGS84（社区解释）', 'GCJ-02（社区解释）')):
        return False
    lat, lon = location.get('latitude'), location.get('longitude')
    return (type(lat) in (int, float) and type(lon) in (int, float)
            and math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180 and (lat != 0 or lon != 0))


def _text(value):
    return ' '.join(value.split()) if isinstance(value, str) else ''


def _without_units(value, house_numbers=False):
    units = r'(?:号楼|号院|栋|幢|单元|室|层|楼' + ('|号)' if house_numbers else ')')
    text = re.split(r'(?:\d+(?:[-－]\d+)?|[一二三四五六七八九十百零〇]+)' + units,
                    _text(value), maxsplit=1)[0].strip()
    return re.sub(r'\d+号$', '', text).strip()


def short_address(regeocode):
    """Prefer district and a named place or road; omit postal/unit detail."""
    if not isinstance(regeocode, dict):
        return None
    component = regeocode.get('addressComponent')
    if isinstance(component, dict):
        district = _text(component.get('district'))
        candidates = []
        for field, key in (('neighborhood', 'name'), ('building', 'name'), ('streetNumber', 'street')):
            value = component.get(field)
            if isinstance(value, dict):
                candidates.append(_without_units(value.get(key)))
        candidates.append(_without_units(component.get('township')))
        place = next((value for value in candidates if value), '')
        if district or place:
            return '·'.join(dict.fromkeys(value for value in (district, place) if value))[:50]
    text = _text(regeocode.get('formatted_address'))
    text = re.sub(r'^中国', '', text)
    text = re.sub(r'^.+?(?:省|自治区|特别行政区)', '', text)
    text = re.sub(r'^.+?市', '', text)
    match = re.match(r'^(.+?(?:区|县|旗))', text)
    district = match[1] if match else ''
    remainder = text[len(district):]
    road = re.match(r'^.+?(?:大道|公路|大街|路|街|巷|弄|条)', remainder)
    place = road[0] if road else _without_units(remainder, house_numbers=True)
    return '·'.join(value for value in (district, place) if value)[:50] or None


class AmapGeocoder:
    def __init__(self, config_path):
        self.config_path = config_path

    def _request(self, path, params):
        request = Request('https://restapi.amap.com' + path + '?' + urlencode(params),
                          headers={'Accept': 'application/json'})
        with build_opener(NoRedirect()).open(request, timeout=5) as response:
            return json.loads(response.read(65536))

    def __call__(self, location, *, estimate=False):
        # Notification lookups require trusted coordinates. The overview may explicitly
        # request an estimate from valid coordinates without changing their trust flag.
        try:
            if not is_trusted_location(dict(location, trusted=True) if estimate and isinstance(location, dict) else location):
                return None
            system = location.get('coordinate_system')
            lat, lon = location.get('latitude'), location.get('longitude')
            key = load(self.config_path).get('api_key', '').strip()
            if not key:
                return None
            coordinates = '%.6f,%.6f' % (lon, lat)
            if system == 'WGS84（社区解释）':
                converted = self._request('/v3/assistant/coordinate/convert',
                    {'key': key, 'locations': coordinates, 'coordsys': 'gps', 'output': 'JSON'})
                if not isinstance(converted, dict) or converted.get('status') != '1':
                    return None
                coordinates = converted.get('locations')
                if not isinstance(coordinates, str):
                    return None
                x, y = map(float, coordinates.split(','))
                if not -180 <= x <= 180 or not -90 <= y <= 90:
                    return None
            result = self._request('/v3/geocode/regeo',
                {'key': key, 'location': coordinates, 'extensions': 'all' if estimate else 'base', 'output': 'JSON'})
            if not isinstance(result, dict) or result.get('status') != '1':
                return None
            regeocode = result.get('regeocode')
            if estimate and isinstance(regeocode, dict):
                landmarks = []
                for poi in regeocode.get('pois', []) if isinstance(regeocode.get('pois'), list) else []:
                    if not isinstance(poi, dict):
                        continue
                    try:
                        distance = float(poi.get('distance'))
                    except (TypeError, ValueError):
                        continue
                    name = _without_units(poi.get('name'))
                    if name and math.isfinite(distance) and 0 <= distance <= 500:
                        landmarks.append((distance, name))
                if landmarks:
                    return min(landmarks)[1][:50]
            return short_address(regeocode)
        except Exception:
            # Provider errors can contain the key or coordinates; never log them.
            return None
