"""Notification layout and routing; no real Bark or vehicle requests."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.notifications import BarkSender, bark_channel
from zeekr_control.monitor import bark_message_for
from zeekr_control.system_notifications import AuthFailureAlert


class BarkLayoutTests(unittest.TestCase):
    def test_categories_keep_recipient_and_delivery_level_but_split_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bark.json'
            path.write_text(json.dumps(dict(base_url='https://example.com/bark',device_key='SYNTHETIC_DEVICE')))
            path.chmod(0o600)
            captured=[]
            class Opener:
                def open(self,request,timeout):
                    captured.append(json.loads(request.data));return io.BytesIO(b'{"code":200}')
            sender=BarkSender(path)
            with patch('zeekr_control.notifications.build_opener',return_value=Opener()):
                for category in ('trip','charge','reminder','collection','service','storage'):
                    bark_channel(sender,category)('合成标题','合成正文')
            self.assertEqual(len({row['group'] for row in captured}),6)
            self.assertTrue(all(row['group'].startswith('极氪 · ') for row in captured))
            self.assertTrue(all(row['device_key']=='SYNTHETIC_DEVICE' and row['level']=='active' for row in captured))

    def test_fake_sender_keeps_two_argument_protocol(self):
        calls=[];sender=lambda title,body:calls.append((title,body))
        bark_channel(sender,'trip')('标题','正文')
        self.assertEqual(calls,[('标题','正文')])

    def test_trip_end_preserves_partial_distance_and_soc_and_avoids_delivery_claim(self):
        title,body=bark_message_for('trip_end',dict(start_time=1704067200000,end_time=1704070800000,
            duration_seconds=3600,distance_km=25,start_soc=70,end_soc=60,soc_delta=-10,partial=True))
        self.assertIn('行程结束',title)
        self.assertIn('25 km',body);self.assertIn('70% → 60%',body)
        self.assertIn('部分记录',body);self.assertNotIn('已发送',body)

    def test_unknown_distance_and_bad_soc_do_not_become_zero_or_invalid_numbers(self):
        _,body=bark_message_for('trip_end',dict(end_time=1704070800000,distance_km=None,end_soc=float('inf')))
        self.assertIn('里程未知',body);self.assertNotIn('0 km',body);self.assertNotIn('inf',body)

    def test_1509_retry_and_manual_check_have_distinct_titles(self):
        titles=[]
        for manual in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                calls=[];alert=AuthFailureAlert(Path(folder),lambda *args:calls.append(args))
                alert.blocked('网关代码 1509',1704070800000,manual=manual,reason='合成网关原话')
                alert.deliver();self.assertEqual(len(calls),1)
                titles.append(calls[0][0]);self.assertIn('合成网关原话',calls[0][1])
                self.assertNotIn('服务维护',calls[0][1])
                alert.deliver();self.assertEqual(len(calls),1)
        self.assertNotEqual(*titles)
