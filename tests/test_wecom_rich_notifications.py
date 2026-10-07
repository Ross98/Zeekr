"""Rich WeCom notification tests; no real webhook calls."""
import hashlib
import io
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from zeekr_control.notifications import DeliveryError, WeComSender
from zeekr_control.storage import save


class WeComRichSenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'webhook.json'
        save(self.path, {'webhook_url':
            'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=synthetic-key-for-tests'})

    def test_markdown_uses_provider_payload_and_4096_byte_limit(self):
        payloads = []
        class Opener:
            def open(self, request, timeout):
                payloads.append(json.loads(request.data))
                return io.BytesIO(b'{"errcode":0}')
        with patch('zeekr_control.notifications.build_opener', return_value=Opener()):
            WeComSender(self.path).send_markdown('**行程结束**')
            self.assertEqual(payloads, [{'msgtype':'markdown','markdown':{'content':'**行程结束**'}}])
            WeComSender(self.path).send_markdown('a' * 4096)
            with self.assertRaises(DeliveryError):
                WeComSender(self.path).send_markdown('a' * 4097)

    def test_image_uses_base64_and_binary_md5(self):
        payloads = []
        class Opener:
            def open(self, request, timeout):
                payloads.append(json.loads(request.data))
                return io.BytesIO(b'{"errcode":0}')
        image = b'\x89PNG\r\n\x1a\nsynthetic'
        with patch('zeekr_control.notifications.build_opener', return_value=Opener()):
            WeComSender(self.path).send_image(image)
        self.assertEqual(payloads[0]['msgtype'], 'image')
        self.assertEqual(payloads[0]['image']['md5'], hashlib.md5(image).hexdigest())
        self.assertEqual(payloads[0]['image']['base64'], 'iVBORw0KGgpzeW50aGV0aWM=')


class TripImageTests(unittest.TestCase):
    @staticmethod
    def _solid_png(color):
        def chunk(name, data):
            return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data) & 0xffffffff)
        raw = b'\0' + bytes(color)
        return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

    @staticmethod
    def _palette_png(color):
        def chunk(name, data):
            return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data) & 0xffffffff)
        return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 3, 0, 0, 0))
                + chunk(b'PLTE', bytes(color)) + chunk(b'IDAT', zlib.compress(b'\0\0')) + chunk(b'IEND', b''))

    def _pixel(self, image, x, y):
        offset = 8
        data = b''
        while offset < len(image):
            length = struct.unpack('>I', image[offset:offset + 4])[0]
            name = image[offset + 4:offset + 8]
            value = image[offset + 8:offset + 8 + length]
            offset += 12 + length
            if name == b'IDAT': data += value
            if name == b'IEND': break
        raw = zlib.decompress(data)
        stride = 1068 * 3 + 1
        # Renderer output uses filter 0 for every row.
        self.assertEqual(raw[y * stride], 0)
        start = y * stride + 1 + x * 3
        return tuple(raw[start:start + 3])

    def _region_contains(self,image,left,top,right,bottom,color):
        offset=8;data=b''
        while offset<len(image):
            length=struct.unpack('>I',image[offset:offset+4])[0];name=image[offset+4:offset+8]
            value=image[offset+8:offset+8+length];offset+=12+length
            if name==b'IDAT':data+=value
            if name==b'IEND':break
        raw=zlib.decompress(data);stride=1068*3+1
        return any(tuple(raw[y*stride+1+x*3:y*stride+4+x*3])==color
                   for y in range(top,bottom) for x in range(left,right))

    def test_renderer_composites_provider_map_and_keeps_expected_dimensions(self):
        from zeekr_control.trip_notification_image import render_trip_png
        report = {'metrics': {'distance_km': 23.6, 'duration_seconds': 2520,
                              'estimated_kwh_100km': 21.9, 'average_speed_kmh': 33.7},
                  'start': {'soc': 78}, 'end': {'soc': 72}, 'partial': False}
        route = {'segments': [[{'longitude':121.0,'latitude':31.0},
                               {'longitude':121.1,'latitude':31.05},
                               {'longitude':121.2,'latitude':31.02}]], 'gaps': []}
        image = render_trip_png(report, route, self._solid_png((211, 223, 227)))
        self.assertEqual(image[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II', image[16:24]), (1068, 720))
        self.assertEqual(self._pixel(image, 500, 200), (211, 223, 227))
        self.assertLess(len(image), 2 * 1024 * 1024)

    def test_renderer_rejects_missing_or_invalid_map_instead_of_drawing_fake_map(self):
        from zeekr_control.trip_notification_image import render_trip_png
        with self.assertRaisesRegex(ValueError, '真实地图'):
            render_trip_png({}, {'segments': []}, None)
        with self.assertRaisesRegex(ValueError, '真实地图'):
            render_trip_png({}, {'segments': []}, b'not-png')

    def test_renderer_accepts_palette_png_returned_by_amap(self):
        from zeekr_control.trip_notification_image import render_trip_png
        image=render_trip_png({}, {'segments': []}, self._palette_png((211,223,227)))
        self.assertEqual(self._pixel(image,500,200),(211,223,227))

    def test_metric_values_never_draw_into_card_gutters(self):
        from zeekr_control.trip_notification_image import render_trip_png, COLORS
        report={'metrics':{'distance_km':10,'duration_seconds':1668,'estimated_kwh_100km':None},
                'start':{'soc':55},'end':{'soc':53},'partial':False}
        image=render_trip_png(report,{'segments':[]},self._solid_png((211,223,227)))
        for left,right in ((280,295),(519,534),(758,773)):
            self.assertFalse(self._region_contains(image,left,535,right,590,COLORS['white']))


class AmapStaticMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'amap-geocoding.json'
        save(self.config, {'api_key': 'synthetic-key'})

    def test_converts_wgs84_and_requests_static_map_with_broken_segments_preserved(self):
        from zeekr_control.trip_map import AmapStaticMap
        calls=[]
        route={'segments': [
            [{'longitude':121.0,'latitude':31.0,'trusted':True,'coordinate_system':'WGS84（社区解释）'},
             {'longitude':121.1,'latitude':31.1,'trusted':True,'coordinate_system':'WGS84（社区解释）'}],
            [{'longitude':121.2,'latitude':31.2,'trusted':True,'coordinate_system':'WGS84（社区解释）'},
             {'longitude':121.3,'latitude':31.3,'trusted':True,'coordinate_system':'WGS84（社区解释）'}]]}
        provider=AmapStaticMap(self.config)
        def request(path,params,binary=False):
            calls.append((path,params,binary))
            if path.endswith('/convert'):
                values=params['locations'].split('|')
                return {'status':'1','locations':';'.join('%.6f,%.6f'%(float(v.split(',')[0])+.004,float(v.split(',')[1])-.002) for v in values)}
            return self._png
        self._png=TripImageTests._solid_png((1,2,3))
        with patch.object(provider,'_request',side_effect=request):
            self.assertEqual(provider(route),self._png)
        self.assertEqual(calls[0][0],'/v3/assistant/coordinate/convert')
        static=calls[-1]
        self.assertEqual(static[0],'/v3/staticmap')
        self.assertTrue(static[2])
        self.assertEqual(static[1]['size'],'956*302')
        self.assertEqual(static[1]['scale'],2)
        self.assertEqual(static[1]['paths'].count('|'),1)
        self.assertIn('121.004000,30.998000',static[1]['paths'])
        self.assertIn('A:121.004000,30.998000',static[1]['markers'])
        self.assertIn('B:121.304000,31.298000',static[1]['markers'])

    def test_missing_key_untrusted_unknown_too_many_segments_and_provider_errors_fail_closed(self):
        from zeekr_control.trip_map import AmapStaticMap
        base={'longitude':121.0,'latitude':31.0,'trusted':True,'coordinate_system':'GCJ-02（社区解释）'}
        provider=AmapStaticMap(self.config)
        for route in ({'segments':[]}, {'segments':[[dict(base,trusted=False),dict(base)]]},
                      {'segments':[[dict(base,coordinate_system='未知'),dict(base)]]},
                      {'segments':[[dict(base),dict(base)]]*5}):
            with self.assertRaises(ValueError): provider(route)
        self.config.unlink()
        with self.assertRaises(ValueError): provider({'segments':[[dict(base),dict(base)]]})
        save(self.config, {'api_key':'synthetic-key'})
        with patch.object(provider,'_request',return_value=b'not-png'):
            with self.assertRaises(ValueError): provider({'segments':[[dict(base),dict(base)]]})

    def test_long_route_is_bounded_without_dropping_segment_endpoints(self):
        from zeekr_control.trip_map import AmapStaticMap
        provider=AmapStaticMap(self.config);calls=[]
        points=[{'longitude':121+i/10000,'latitude':31+i/10000,'trusted':True,
                 'coordinate_system':'GCJ-02（社区解释）'} for i in range(300)]
        image=TripImageTests._solid_png((1,2,3))
        def request(path,params,binary=False):
            calls.append((path,params));return image
        with patch.object(provider,'_request',side_effect=request): provider({'segments':[points]})
        path=calls[-1][1]['paths']
        self.assertLessEqual(path.count(';')+1,120)
        self.assertIn('121.000000,31.000000',path)
        self.assertIn('121.029900,31.029900',path)


class MarkdownFormattingTests(unittest.TestCase):
    def test_report_title_sections_and_cache_note_are_emphasized(self):
        from zeekr_control.report_markdown import markdown_for
        source = ('🚗 行程结束｜23.6 公里 · 42 分钟\n\n【电量与续航】\n'
                  '电量：78% → 72%（变化 -6 个百分点）\n'
                  '状态来自车辆云端缓存，时间可能延迟。\n编号：abc123')
        result = markdown_for(source)
        self.assertIn('## 🚗 行程结束｜23.6 公里 · 42 分钟', result)
        self.assertIn('**电量与续航**', result)
        self.assertIn('电量：78% → 72%（下降 6 个百分点）', result)
        self.assertIn('<font color="comment">状态来自车辆云端缓存，时间可能延迟。</font>', result)


class RichDeliveryTests(unittest.TestCase):
    def setUp(self):
        from zeekr_control.monitor import Monitor
        from tests.test_monitor import BASE, sample
        self.BASE, self.sample = BASE, sample
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.maps=[]
        self.monitor = Monitor(Path(self.temp.name) / 'private' / 'tracks.sqlite3',
                               map_renderer=lambda route:(self.maps.append(route) or TripImageTests._solid_png((220,225,230))))

    def _trip(self):
        for seconds, kwargs in ((0,{}),(60,{'speed':30,'engine':'engine_on','ready':1,'km':101}),
                                (120,{'km':110,'soc':76})):
            raw=self.sample(seconds,**kwargs)
            raw['position']['longitude'] += seconds*1000
            self.monitor.tracks.record('test-vehicle',raw,self.BASE+seconds*1000,180)
            self.monitor.observe('test-vehicle',raw,self.BASE+seconds*1000)
        parked=self.sample(120,km=110,soc=76)
        for seconds in range(180,721,60):
            self.monitor.observe('test-vehicle',parked,self.BASE+seconds*1000)

    def test_focused_renderer_receives_raw_route_and_resolved_start_name(self):
        self._trip()
        calls=[]
        class Renderer:
            def render_trip(self,report,route,name):
                calls.append((report,route,name));return TripImageTests._solid_png((220,225,230))
        class Sender:
            def send_markdown(self,value): pass
            def send_image(self,value): pass
        self.monitor.map_renderer=Renderer()
        self.monitor.address_resolver=lambda location:'合成起点'
        self.monitor.deliver(Sender(),self.BASE+720000)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][2],'合成起点')
        self.assertGreaterEqual(len(calls[0][1]['segments'][0]),2)
        self.monitor.deliver(Sender(),self.BASE+900000)
        self.assertEqual(len(calls),1)

    def test_trip_sends_markdown_then_png_once(self):
        self._trip()
        class Sender:
            def __init__(self): self.calls=[]
            def send_markdown(self,value): self.calls.append(('markdown',value))
            def send_image(self,value): self.calls.append(('image',value))
        sender=Sender(); self.monitor.deliver(sender,self.BASE+720000)
        self.assertEqual([kind for kind,_ in sender.calls],['markdown','image'])
        self.assertTrue(sender.calls[0][1].startswith('## 🚗 行程结束'))
        self.assertTrue(sender.calls[1][1].startswith(b'\x89PNG'))
        self.assertEqual(len(self.maps),1)
        self.assertGreaterEqual(len(self.maps[0]['segments'][0]),2)
        self.monitor.deliver(sender,self.BASE+900000)
        self.assertEqual(len(sender.calls),2)
        event=self.monitor.events()[0]
        self.assertEqual((event['delivery'],event['image_delivery']),('sent','sent'))

    def test_image_failure_never_repeats_successful_markdown(self):
        self._trip()
        class Sender:
            def __init__(self): self.markdowns=0; self.images=0
            def send_markdown(self,value): self.markdowns+=1
            def send_image(self,value):
                self.images+=1
                raise DeliveryError('图片被拒绝',permanent=True)
        sender=Sender(); self.monitor.deliver(sender,self.BASE+720000)
        self.monitor.deliver(sender,self.BASE+900000)
        self.assertEqual((sender.markdowns,sender.images),(1,1))
        event=self.monitor.events()[0]
        self.assertEqual((event['delivery'],event['image_delivery']),('sent','failed'))
        self.assertEqual(event['image_error'],'图片被拒绝')

    def test_map_failure_never_sends_fake_image(self):
        self._trip()
        def fail(_route): raise ValueError('真实地图服务不可用')
        self.monitor.map_renderer=fail
        class Sender:
            def __init__(self): self.calls=[]
            def send_markdown(self,value): self.calls.append('markdown')
            def send_image(self,value): self.calls.append('image')
        sender=Sender();self.monitor.deliver(sender,self.BASE+720000)
        self.assertEqual(sender.calls,['markdown'])
        event=self.monitor.events()[0]
        self.assertEqual(event['image_delivery'],'pending')
        self.assertEqual(event['image_error'],'行程图片准备失败，未调用发送器')

    def test_preparation_retries_with_backoff_then_stops_after_three_attempts(self):
        self._trip()
        from zeekr_control.focused_trip_image import ImagePreparationError
        calls=[]
        class Renderer:
            def render_trip(self,*args):
                calls.append('render');raise ImagePreparationError('行程图片超时')
        class Sender:
            def send_markdown(self,value): calls.append('markdown')
            def send_image(self,value): calls.append('image')
        self.monitor.map_renderer=Renderer();sender=Sender();now=self.BASE+720000
        self.monitor.deliver(sender,now)
        self.monitor.deliver(sender,now+59999)
        self.assertEqual(calls,['markdown','render'])
        from zeekr_control.monitor import Monitor
        self.monitor=Monitor(self.monitor.tracks.path,map_renderer=Renderer())
        self.monitor.deliver(sender,now+60000)
        self.monitor.deliver(sender,now+179999)
        self.assertEqual(calls,['markdown','render','render'])
        self.monitor.deliver(sender,now+180000)
        self.monitor.deliver(sender,now+900000)
        self.assertEqual(calls,['markdown','render','render','render'])
        event=self.monitor.events()[0]
        self.assertEqual(event['image_delivery'],'failed');self.assertEqual(event['image_error'],'行程图片超时，未调用发送器')

    def test_preparation_retry_succeeds_without_resending_text(self):
        self._trip();calls=[]
        class Renderer:
            def render_trip(self,*args):
                calls.append('render')
                if calls.count('render')==1:raise RuntimeError('private-secret')
                return b'png'
        class Sender:
            def send_markdown(self,value):calls.append('markdown')
            def send_image(self,value):calls.append('image')
        self.monitor.map_renderer=Renderer();sender=Sender();now=self.BASE+720000
        self.monitor.deliver(sender,now);self.monitor.deliver(sender,now+60000);self.monitor.deliver(sender,now+900000)
        self.assertEqual(calls,['markdown','render','render','image'])
        self.assertEqual(self.monitor.events()[0]['image_delivery'],'sent')

    def test_invalid_route_is_terminal_and_ambiguous_send_is_never_retried(self):
        from zeekr_control.focused_trip_image import ImagePreparationError
        self._trip();calls=[]
        class Renderer:
            def render_trip(self,*args):raise ImagePreparationError('行程图片轨迹或输入无效',retryable=False)
        class Sender:
            def send_markdown(self,value):calls.append('markdown')
            def send_image(self,value):calls.append('image');raise RuntimeError('private-secret')
        sender=Sender();self.monitor.map_renderer=Renderer();now=self.BASE+720000
        self.monitor.deliver(sender,now);self.monitor.deliver(sender,now+900000)
        self.assertEqual(calls,['markdown']);self.assertEqual(self.monitor.events()[0]['image_delivery'],'failed')
        with self.monitor.tracks.connect() as db:db.execute("UPDATE monitor_event_media SET delivery='pending',next_attempt=0")
        self.monitor.map_renderer=lambda route:TripImageTests._solid_png((220,225,230))
        self.monitor.deliver(sender,now+1000000);self.monitor.deliver(sender,now+2000000)
        self.assertEqual(calls,['markdown','image']);self.assertEqual(self.monitor.events()[0]['image_delivery'],'uncertain')


if __name__ == '__main__':
    unittest.main()
