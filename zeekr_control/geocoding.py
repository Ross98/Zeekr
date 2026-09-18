"""Optional Chinese addresses via Amap; failures must not suppress notifications."""
import json
import math
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .notifications import NoRedirect
from .storage import load


class AmapGeocoder:
    def __init__(self, config_path):
        self.config_path = config_path

    def _request(self, path, params):
        request = Request('https://restapi.amap.com' + path + '?' + urlencode(params),
                          headers={'Accept': 'application/json'})
        with build_opener(NoRedirect()).open(request, timeout=5) as response:
            return json.loads(response.read(65536))

    def __call__(self, location):
        # Never guess a coordinate system or send untrusted positions to a provider.
        try:
            if not isinstance(location, dict) or location.get('valid') is not True or location.get('trusted') is not True:
                return None
            system = location.get('coordinate_system')
            if system not in ('WGS84（社区解释）', 'GCJ-02（社区解释）'):
                return None
            lat, lon = location.get('latitude'), location.get('longitude')
            if (type(lat) not in (int, float) or type(lon) not in (int, float)
                    or not math.isfinite(lat) or not math.isfinite(lon)
                    or not -90 <= lat <= 90 or not -180 <= lon <= 180 or (lat == 0 and lon == 0)):
                return None
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
                {'key': key, 'location': coordinates, 'extensions': 'base', 'output': 'JSON'})
            if not isinstance(result, dict) or result.get('status') != '1':
                return None
            address = result.get('regeocode', {}).get('formatted_address')
            if not isinstance(address, str):
                return None
            return ' '.join(address.split())[:100] or None
        except Exception:
            # Provider errors can contain the key or coordinates; never log them.
            return None
