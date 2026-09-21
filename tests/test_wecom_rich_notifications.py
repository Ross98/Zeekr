"""Rich WeCom notification tests; no real webhook calls."""
import hashlib
import io
import json
import struct
import tempfile
import unittest
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
    def test_renderer_returns_bounded_png_with_expected_dimensions(self):
        from zeekr_control.trip_notification_image import render_trip_png
        report = {'metrics': {'distance_km': 23.6, 'duration_seconds': 2520,
                              'estimated_kwh_100km': 21.9, 'average_speed_kmh': 33.7},
                  'start': {'soc': 78}, 'end': {'soc': 72}, 'partial': False}
        route = {'segments': [[{'longitude':121.0,'latitude':31.0},
                               {'longitude':121.1,'latitude':31.05},
                               {'longitude':121.2,'latitude':31.02}]], 'gaps': []}
        image = render_trip_png(report, route)
        self.assertEqual(image[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II', image[16:24]), (1068, 720))
        self.assertLess(len(image), 2 * 1024 * 1024)


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
        self.monitor = Monitor(Path(self.temp.name) / 'private' / 'tracks.sqlite3')

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


if __name__ == '__main__':
    unittest.main()
