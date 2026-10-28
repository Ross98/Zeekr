"""Offline network classifications, health evidence and mileage preservation."""
import errno
import socket
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from zeekr_control.client import transport
from zeekr_control.errors import ApiError


class NetworkRecoveryTests(unittest.TestCase):
    def test_official_transport_avoids_system_proxy_without_replaying_request(self):
        from urllib.request import ProxyHandler
        with patch('zeekr_control.client.build_opener') as opener:
            opener.return_value.open.side_effect=URLError(socket.timeout('PRIVATE-SECRET'))
            with self.assertRaises(ApiError) as caught:
                transport('PUT','https://api.zeekrline.com/auth/account/session/secure',{},b'PRIVATE-TOKEN')
        self.assertEqual(opener.return_value.open.call_count,1)
        self.assertTrue(any(isinstance(h,ProxyHandler) and h.proxies=={} for h in opener.call_args.args))
        self.assertEqual(caught.exception.network_code,'timeout')
        self.assertNotIn('PRIVATE',str(caught.exception))

    def test_network_failures_keep_fixed_diagnostic_codes_not_private_messages(self):
        cases=[(socket.gaierror(-2,'PRIVATE-DNS'),'dns'),
               (ConnectionRefusedError(errno.ECONNREFUSED,'PRIVATE-PROXY'),'connection_refused'),
               (ssl.SSLCertVerificationError(1,'PRIVATE-CERT'),'certificate'),
               (ssl.SSLError('PRIVATE-TLS'),'tls')]
        for reason,code in cases:
            with self.subTest(code=code),patch('zeekr_control.client.build_opener') as opener:
                opener.return_value.open.side_effect=URLError(reason)
                with self.assertRaises(ApiError) as caught:transport('GET','https://api.zeekrline.com/',{},None)
                self.assertEqual(caught.exception.network_code,code)
                self.assertNotIn('PRIVATE',str(caught.exception))

    def test_live_heartbeat_does_not_hide_failed_collection(self):
        from zeekr_control.resource_monitor import collection_health
        from zeekr_control.resource_conditions import observations
        from zeekr_control.storage import save
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private'
            save(root/'monitor-health.json',dict(status='retrying',heartbeat='1000000',
                 last_success='600000',error='网络或 TLS 连接失败',next_check='1060000'))
            health=collection_health(root,1000)
            self.assertTrue(health['online'])
            self.assertFalse(health['readable'])
            state=observations({'collection_health':health})
            self.assertEqual(state['collector']['observed'],'critical')

    def test_old_network_diagnostic_is_not_reused_for_a_new_http_failure(self):
        from zeekr_control.resource_monitor import collection_health
        from zeekr_control.storage import save
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private'
            save(root/'monitor-health.json',dict(status='retrying',heartbeat='1000000',
                 last_success='600000',error='网关 HTTP 503',network_error_code='timeout',
                 network_error_at='500000'))
            self.assertIsNone(collection_health(root,1000)['network_code'])
