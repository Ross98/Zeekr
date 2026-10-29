"""Synthetic provider acknowledgements; no real notifications are sent."""
import io
import socket
import ssl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError, URLError

from zeekr_control.notifications import BarkSender, WeComSender, DeliveryError, FallbackSender
from zeekr_control.storage import save


class NotificationResponseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.root = root
        bark, wecom = root/'bark.json', root/'wecom.json'
        save(bark,dict(base_url='https://synthetic.invalid',device_key='SYNTHETIC_PRIVATE_KEY'))
        save(wecom,dict(webhook_url='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SYNTHETIC_PRIVATE_KEY'))
        self.senders = [(BarkSender(bark),b'{"code":200}'),(WeComSender(wecom),b'{"errcode":0}')]

    def invoke(self, sender, encoded):
        opener = Mock()
        opener.open.return_value = io.BytesIO(encoded)
        with patch('zeekr_control.notifications.build_opener',return_value=opener):
            sender('合成通知')
        return opener

    def test_wecom_connection_failures_have_safe_specific_diagnostics(self):
        cases = [(socket.gaierror('PRIVATE_KEY'), 'DNS', False, False),
                 (ConnectionRefusedError('PRIVATE_KEY'), '连接被拒绝', False, False),
                 (ssl.SSLCertVerificationError('PRIVATE_KEY'), '证书', False, True),
                 (TimeoutError('PRIVATE_KEY'), '超时', True, False),
                 (ssl.SSLError('PRIVATE_KEY'), 'TLS', True, False),
                 (ConnectionResetError('PRIVATE_KEY'), '连接中断', True, False)]
        for reason, label, ambiguous, permanent in cases:
            with self.subTest(reason=type(reason).__name__):
                opener = Mock()
                opener.open.side_effect = URLError(reason)
                with patch('zeekr_control.notifications.build_opener', return_value=opener):
                    with self.assertRaises(DeliveryError) as caught:
                        self.senders[1][0]('合成通知')
                error = caught.exception
                self.assertIn(label, str(error))
                self.assertNotIn('PRIVATE', str(error))
                self.assertEqual((error.ambiguous, error.permanent), (ambiguous, permanent))
                self.assertEqual(error.retry_ambiguous, ambiguous)
                self.assertEqual(opener.open.call_count, 1)

    def test_wecom_response_read_failure_remains_ambiguous(self):
        opener = MagicMock()
        response = Mock()
        response.read.side_effect = ConnectionRefusedError('PRIVATE_RESPONSE')
        opener.open.return_value.__enter__.return_value = response
        with patch('zeekr_control.notifications.build_opener', return_value=opener):
            with self.assertRaises(DeliveryError) as caught:
                self.senders[1][0]('合成通知')
        self.assertTrue(caught.exception.ambiguous)
        self.assertTrue(caught.exception.retry_ambiguous)
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_wecom_server_error_allows_bounded_retry_but_invalid_ack_does_not(self):
        opener = Mock()
        opener.open.side_effect = HTTPError('PRIVATE_URL', 503, 'PRIVATE_BODY', {}, None)
        with patch('zeekr_control.notifications.build_opener', return_value=opener):
            with self.assertRaises(DeliveryError) as caught:
                self.senders[1][0]('合成通知')
        self.assertTrue(caught.exception.retry_ambiguous)
        with self.assertRaises(DeliveryError) as caught:
            self.invoke(self.senders[1][0], b'PRIVATE_INVALID_JSON')
        self.assertTrue(caught.exception.ambiguous)
        self.assertFalse(caught.exception.retry_ambiguous)

    def test_retry_policy_preserves_generic_ambiguity_and_stops_at_limit(self):
        self.assertEqual(DeliveryError('unknown', ambiguous=True).retry_state(0), 'uncertain')
        retry = DeliveryError('timeout', ambiguous=True, retry_ambiguous=True)
        self.assertEqual([retry.retry_state(n) for n in (0, 1, 5)], ['pending', 'uncertain', 'uncertain'])
        self.assertEqual(DeliveryError('certificate', permanent=True).retry_state(0), 'failed')
        safe = DeliveryError('dns')
        self.assertEqual((safe.retry_state(0), safe.retry_state(5)), ('pending', 'failed'))

    def test_success_prefix_does_not_confirm_an_oversized_incomplete_response(self):
        for sender, prefix in self.senders:
            with self.subTest(sender=type(sender).__name__):
                encoded = prefix+b' '*(65536-len(prefix))+b'PRIVATE_INVALID_TRAILER'
                with self.assertRaises(DeliveryError) as caught:
                    self.invoke(sender,encoded)
                self.assertTrue(caught.exception.ambiguous)
                self.assertFalse(caught.exception.permanent)
                self.assertNotIn('PRIVATE',str(caught.exception))

    def test_valid_response_at_exact_limit_is_accepted(self):
        for sender, prefix in self.senders:
            with self.subTest(sender=type(sender).__name__):
                self.invoke(sender,prefix+b' '*(65536-len(prefix)))

    def test_deep_json_is_an_ambiguous_delivery_error(self):
        for sender, _ in self.senders:
            with self.subTest(sender=type(sender).__name__):
                with self.assertRaises(DeliveryError) as caught:
                    self.invoke(sender,b'['*10000+b'0'+b']'*10000)
                self.assertTrue(caught.exception.ambiguous)

    def test_oversized_bark_response_does_not_trigger_fallback_delivery(self):
        bark, prefix = self.senders[0]
        fallback = Mock()
        sender = FallbackSender(bark,fallback)
        with self.assertRaises(DeliveryError) as caught:
            self.invoke(sender,prefix+b' '*(65536-len(prefix))+b'PRIVATE_TRAILER')
        self.assertTrue(caught.exception.ambiguous)
        fallback.assert_not_called()

    def test_event_delivery_stays_uncertain_and_does_not_resend_after_truncated_ack(self):
        from zeekr_control.monitor import Monitor
        monitor = Monitor(self.root/'tracks.sqlite3')
        base = 1789970000000
        data = dict(start_time=base,end_time=base+60000,duration_seconds=60,distance_km=1.2,
                    start_soc=50,end_soc=49,soc_delta=-1,partial=False,start_location=None,
                    end_location=None,start_address=None,end_address=None,addresses_resolved=True)
        with monitor.tracks.connect() as db:
            monitor._event(db,'car','charge_start',data,base+120000)
        bark, prefix = self.senders[0]
        calls = []
        class Opener:
            def open(self,request,timeout):
                calls.append(True)
                return io.BytesIO(prefix+b' '*(65536-len(prefix))+b'PRIVATE_TRAILER')
        with patch('zeekr_control.notifications.build_opener',return_value=Opener()):
            monitor.deliver(lambda message:None,base+180000,alert_sender=bark)
            monitor.deliver(lambda message:None,base+240000,alert_sender=bark)
        event = monitor.events()[0]
        self.assertEqual((event['alert_delivery'],event['delivery']),('uncertain','uncertain'))
        self.assertEqual(calls,[True])
