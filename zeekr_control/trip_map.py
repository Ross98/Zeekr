"""Bounded Amap static maps for completed-trip notification images."""
import json
import math
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .notifications import NoRedirect
from .storage import load


class AmapStaticMap:
    def __init__(self, config_path):
        self.config_path = config_path

    def _request(self, path, params, binary=False):
        request = Request('https://restapi.amap.com' + path + '?' + urlencode(params),
                          headers={'Accept': 'image/png' if binary else 'application/json'})
        with build_opener(NoRedirect()).open(request, timeout=5) as response:
            content = response.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise ValueError('静态地图响应过大')
        return content if binary else json.loads(content)

    @staticmethod
    def _point(value):
        if not isinstance(value, dict) or value.get('trusted') is not True:
            raise ValueError('行程位置不可信')
        system = value.get('coordinate_system')
        if system not in ('WGS84（社区解释）', 'GCJ-02（社区解释）'):
            raise ValueError('行程坐标系未知')
        lon, lat = value.get('longitude'), value.get('latitude')
        if (type(lon) not in (int, float) or type(lat) not in (int, float)
                or not math.isfinite(lon) or not math.isfinite(lat)
                or not -180 <= lon <= 180 or not -90 <= lat <= 90 or (lon == 0 and lat == 0)):
            raise ValueError('行程位置无效')
        return lon, lat, system

    @staticmethod
    def _bounded(points, limit):
        if len(points) <= limit:
            return points
        return [points[round(index * (len(points) - 1) / (limit - 1))] for index in range(limit)]

    def position(self, location, zoom=15):
        """Draw a cached candidate position; preserve its original trust flag."""
        if type(zoom) is not int or not 3 <= zoom <= 17:
            raise ValueError('地图缩放级别无效')
        if not isinstance(location, dict) or location.get('valid') is not True:
            raise ValueError('车辆未返回有效位置')
        lon, lat, system = self._point(dict(location, trusted=True))
        key = load(self.config_path).get('api_key', '').strip()
        if not key:
            raise ValueError('未配置高德 Web 服务 Key')
        if system == 'WGS84（社区解释）':
            result = self._request('/v3/assistant/coordinate/convert',
                {'key': key, 'locations': '%.6f,%.6f' % (lon, lat), 'coordsys': 'gps', 'output': 'JSON'})
            try:
                if not isinstance(result, dict) or result.get('status') != '1':
                    raise ValueError()
                lon, lat = map(float, result['locations'].split(','))
                self._point(dict(trusted=True, longitude=lon, latitude=lat, coordinate_system='GCJ-02（社区解释）'))
            except (KeyError, TypeError, ValueError):
                raise ValueError('高德坐标转换失败') from None
        point = '%.6f,%.6f' % (lon, lat)
        color = '0x20776e' if location.get('trusted') is True else '0x7e898a'
        image = self._request('/v3/staticmap', {'key': key, 'location': point, 'zoom': zoom,
            'size': '750*400', 'scale': 2, 'markers': 'mid,%s,:%s' % (color, point), 'traffic': 0}, binary=True)
        if not isinstance(image, bytes) or not image.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('高德底图暂不可用，请稍后重试')
        return image

    def __call__(self, route):
        key = load(self.config_path).get('api_key', '').strip()
        if not key:
            raise ValueError('未配置高德 Web 服务 Key')
        source = route.get('segments') if isinstance(route, dict) else None
        if not isinstance(source, list) or not source or len(source) > 4:
            raise ValueError('静态地图仅支持一至四段可信轨迹')
        parsed = []
        per_segment = 120 // len(source)
        for segment in source:
            points = [self._point(point) for point in self._bounded(segment, per_segment)]
            if len(points) < 2:
                raise ValueError('轨迹片段点数不足')
            parsed.append(points)
        flat = [point for segment in parsed for point in segment]
        converted = []
        for offset in range(0, len(flat), 40):
            batch = flat[offset:offset + 40]
            if len({point[2] for point in batch}) != 1:
                raise ValueError('单批轨迹坐标系不一致')
            if batch[0][2] == 'GCJ-02（社区解释）':
                converted.extend((point[0], point[1]) for point in batch)
                continue
            locations = '|'.join('%.6f,%.6f' % (point[0], point[1]) for point in batch)
            result = self._request('/v3/assistant/coordinate/convert',
                                   {'key': key, 'locations': locations, 'coordsys': 'gps', 'output': 'JSON'})
            text = result.get('locations') if isinstance(result, dict) and result.get('status') == '1' else None
            values = text.split(';') if isinstance(text, str) else []
            if len(values) != len(batch):
                raise ValueError('高德坐标转换失败')
            try:
                converted.extend(tuple(map(float, value.split(','))) for value in values)
            except (TypeError, ValueError):
                raise ValueError('高德坐标转换失败') from None
        rebuilt, cursor = [], 0
        for segment in parsed:
            rebuilt.append(converted[cursor:cursor + len(segment)])
            cursor += len(segment)
        def encoded(points):
            return ';'.join('%.6f,%.6f' % point for point in points)
        paths = '|'.join('6,0x00a990,1,,:'.join(('', encoded(segment))) for segment in rebuilt)
        first, last = rebuilt[0][0], rebuilt[-1][-1]
        markers = 'mid,0x00a990,A:%s|mid,0xffa500,B:%s' % (encoded([first]), encoded([last]))
        image = self._request('/v3/staticmap', {'key': key, 'size': '956*302', 'scale': 2,
                              'paths': paths, 'markers': markers, 'traffic': 0}, binary=True)
        if not isinstance(image, bytes) or not image.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('高德未返回有效真实地图')
        return image
