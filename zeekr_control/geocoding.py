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


def named_place_name(value):
    """Reject automatic road/direction labels, preserving real POI branch names."""
    name = _without_units(value).strip('· ')
    if name.endswith('附近'):
        name = name[:-2].rstrip()
    tail = name.rsplit('·', 1)[-1]
    if (not tail or tail in ('未知', '位置未知', '道路')
            or re.search(r'交叉口|路口|(?:\d+(?:\.\d+)?)\s*(?:km|公里|千米|米)(?:附近)?', tail, re.I)
            or re.search(r'(?:大道|公路|大街|路|街|巷|弄|条)(?:\d+号.*|[东西南北]+(?:侧|面|方向)?)?$', tail)
            or (re.search(r'(?:省|市|区|县|旗|乡|镇|街道)$', tail)
                and not re.search(r'(?:小区|社区|园区|校区|景区|住宅区|街区|[A-Za-z0-9一二三四五六七八九十东西南北中]+区)$', tail))):
        return None
    return name[:50]


def _place_rank(name, kind=''):
    """Specific landmarks, stations, shops, then broad areas."""
    name = re.sub(r'[（(].*?[）)]', '', name)
    if re.search(r'(?:大学城|商圈|片区|开发区|新城区)$', name):
        return 3
    if (kind in ('060100', '060101', '060102', '120100') or kind.startswith(('1202', '1203'))
            or re.search(r'商场|购物中心|住宅区|产业园|学校|医院|公园|风景', kind)):
        return 0
    if kind.startswith(('1505', '1507')) or re.search(r'公交车站|地铁站|火车站|汽车站|港口|机场', kind):
        return 1
    if kind.startswith(('05', '06', '1509')) or re.search(r'餐饮服务|购物服务|停车场', kind):
        return 2
    if re.search(r'小区|社区|园区|公馆|大厦|商场|购物中心|广场|学校|大学|医院|公园|景区', name):
        return 0
    if re.search(r'(?:站|站台|机场)$', name):
        return 1
    return 2


def _candidate(value):
    if not isinstance(value, dict):
        return None
    name = named_place_name(value.get('name'))
    kind = _text(value.get('type'))
    if not name or '地名地址' in kind:
        return None
    distance = value.get('distance')
    if isinstance(distance, bool):
        return None
    try:
        distance = float(distance)
    except (TypeError, ValueError):
        return None
    rank = _place_rank(name, kind)
    if not math.isfinite(distance) or not 0 <= distance <= (150 if rank == 2 else 300):
        return None
    return rank, distance, name


def _area_size(value):
    """Unknown/invalid AOI areas cannot outrank a known smaller area."""
    if isinstance(value, bool):
        return math.inf
    try:
        area = float(value)
    except (TypeError, ValueError):
        return math.inf
    return area if math.isfinite(area) and area > 0 else math.inf


def _related_names(first, second):
    """Recognize named parent/subarea relationships, never invent a shared label."""
    if first == second:
        return True
    suffix = r'(?:[A-Za-z0-9一二三四五六七八九十东西南北中]+(?:街区|区|期))+$'
    return bool(re.search(re.escape(first) + suffix, second)
                or re.search(re.escape(second) + suffix, first))


def _select_place(candidates):
    # Merge repeated AOI/POI names. AOI boundary distance and POI centre distance
    # have different meanings, so prefer AOI evidence and compare like sources.
    unique = {}
    for candidate in candidates:
        name = candidate['name']
        old = unique.get(name)
        key = lambda c: (c['source'] != 'aois', c['distance'], c['area'])
        if old is None or key(candidate) < key(old):
            unique[name] = candidate
    candidates = list(unique.values())
    specific = [c for c in candidates if c['rank'] < 3]
    candidates = specific or candidates
    nearest = min(c['distance'] for c in candidates)
    local = [c for c in candidates if c['distance'] <= nearest + 100]
    rank = min(c['rank'] for c in local)
    contenders = [c for c in local if c['rank'] == rank]
    containing = [c for c in contenders if c['source'] == 'aois' and c['distance'] == 0]
    winner = (min(containing, key=lambda c: (c['area'], c['name'])) if containing
              else min(contenders, key=lambda c: (c['distance'], c['name'])))
    if rank != 0:
        return winner['name']
    margin = 15
    comparable_distance = max(3, winner['distance'] * 2)
    conflicts = [c for c in contenders if c['source'] == winner['source']
                 and not _related_names(c['name'], winner['name'])
                 and abs(c['distance'] - winner['distance']) <= margin
                 and c['distance'] <= comparable_distance]
    if not conflicts:
        return winner['name']
    # A known containing parent may safely name conflicting subareas. A broad
    # university city or a fabricated string prefix cannot resolve the conflict.
    parents = [c for c in containing if all(_related_names(c['name'], other['name'])
               for other in [winner, *conflicts])]
    return min(parents, key=lambda c: (c['area'], c['name']))['name'] if parents else None


def short_address(regeocode):
    """Select a named place; unresolved neighbouring landmarks have no guess."""
    if not isinstance(regeocode, dict):
        return None
    candidates = []
    for field in ('aois', 'pois'):
        values = regeocode.get(field)
        for value in values if isinstance(values, list) else []:
            candidate = _candidate(value)
            if candidate is not None:
                rank, distance, name = candidate
                candidates.append(dict(rank=rank, distance=distance, name=name,
                                       source=field, area=_area_size(value.get('area'))))
    component = regeocode.get('addressComponent')
    if isinstance(component, dict):
        for field in ('neighborhood', 'building'):
            value = component.get(field)
            if isinstance(value, dict) and '地名地址' not in _text(value.get('type')):
                name = named_place_name(value.get('name'))
                if name:
                    rank = _place_rank(name, _text(value.get('type')))
                    if rank < 3:
                        return name
                    candidates.append(dict(rank=rank, distance=0, name=name,
                                           source='component', area=math.inf))
    if candidates:
        # An ambiguity deliberately returns None; address/broad-area fallbacks
        # must not turn that result back into a confident-looking name.
        return _select_place(candidates)
    text = _text(regeocode.get('formatted_address'))
    text = re.sub(r'^中国', '', text)
    text = re.sub(r'^.+?(?:省|自治区|特别行政区)', '', text)
    text = re.sub(r'^.+?市', '', text)
    text = re.sub(r'^.+?(?:区|县|旗)', '', text)
    name = named_place_name(text)
    # Free-form addresses have no distance or type evidence. Accept only an
    # identifiable landmark/station, never a raw street/house-number fragment.
    return name if name and _place_rank(name) < 2 and not re.search(r'(?:路|街|巷|弄)\d+号', name) else None


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
                {'key': key, 'location': coordinates, 'extensions': 'all', 'radius': 300, 'output': 'JSON'})
            if not isinstance(result, dict) or result.get('status') != '1':
                return None
            return short_address(result.get('regeocode'))
        except Exception:
            # Provider errors can contain the key or coordinates; never log them.
            return None
