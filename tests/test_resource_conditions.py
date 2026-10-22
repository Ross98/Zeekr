"""Regression evidence for resource alarms; all notifications are synthetic."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from zeekr_control.notifications import DeliveryError
from zeekr_control.resource_monitor import ResourceHealth, NativeSampler, process_sample, parse_processes
from test_resource_monitor import healthy


class ConditionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.sender = Mock()
        self.monitor = ResourceHealth(Path(folder.name), self.sender)

    def ticks(self, sample, start=1000, count=3):
        for i in range(count):
            self.monitor.tick(sample, start+i*60)

    def test_different_causes_cannot_combine_confirmations(self):
        self.monitor.tick(healthy(host_cpu_percent=96), 1000)
        self.monitor.tick(healthy(app_cpu_percent=250), 1060)
        self.monitor.tick(healthy(memory_pressure='critical'), 1120)
        self.sender.assert_not_called()

    def test_unrelated_partial_cpu_does_not_block_host_recovery(self):
        self.ticks(healthy(host_cpu_percent=96))
        self.ticks(healthy(app_cpu_percent=None, app_cpu_complete=False), 1180)
        self.assertNotEqual(self.monitor.cached()['level'], 'critical')
        self.assertIn('恢复', self.sender.call_args.args[0])

    def test_retry_never_reuses_a_reason_that_is_no_longer_observed(self):
        self.sender.side_effect = DeliveryError('synthetic', permanent=False)
        self.ticks(healthy(app_rss_bytes=1100*1024**2))
        self.sender.side_effect = None
        self.ticks(healthy(host_cpu_percent=96), 1180, 16)
        messages = [' '.join(call.args) for call in self.sender.call_args_list[1:]]
        self.assertTrue(messages)
        self.assertTrue(all('Zeekr 进程树内存持续超预算' not in message.splitlines() for message in messages))
        self.assertIn('主机 CPU', messages[-1])

    def test_large_app_alone_is_budget_warning_not_system_pressure(self):
        self.ticks(healthy(app_rss_bytes=2*1024**3, app_cpu_percent=250))
        self.assertEqual(self.monitor.cached()['level'], 'warning')
        title, body = self.sender.call_args.args
        self.assertIn('预算', title)
        self.assertIn('不等于系统内存不足', body)

    def test_new_same_severity_reason_has_own_confirmation_and_notice(self):
        self.ticks(healthy(memory_pressure='warning'))
        self.ticks(healthy(memory_pressure='warning', host_cpu_percent=90), 1180, 2)
        self.assertEqual(self.sender.call_count, 1)
        self.monitor.tick(healthy(memory_pressure='warning', host_cpu_percent=90), 1300)
        self.assertEqual(self.sender.call_count, 2)

    def test_unknown_own_metric_cannot_claim_recovery(self):
        self.ticks(healthy(memory_pressure='critical'))
        self.ticks(healthy(memory_pressure=None, sample_errors=['memory_pressure']), 1180)
        self.assertEqual(self.monitor.cached()['level'], 'critical')
        self.assertNotIn('恢复', self.sender.call_args.args[0])

    def test_critical_hysteresis_has_a_recovery_margin(self):
        self.ticks(healthy(host_cpu_percent=96))
        self.ticks(healthy(host_cpu_percent=94), 1180)
        self.assertEqual(self.monitor.cached()['level'], 'critical')
        self.ticks(healthy(host_cpu_percent=88), 1360)
        self.assertEqual(self.monitor.cached()['level'], 'warning')

    def test_exited_child_time_rolls_into_parent_without_double_counting(self):
        old = parse_processes('501 10 1 100 0:10 01:00\n501 11 10 100 0:20 00:30')
        _, previous = process_sample(old, [10], None, 0)
        new = parse_processes('501 10 1 100 1:30 02:00')
        sample, _ = process_sample(new, [10], previous, 60)
        self.assertEqual(sample['app_cpu_percent'], 100)
        self.assertTrue(sample['app_cpu_complete'])

    def test_between_sample_child_work_is_included_in_parent_counter(self):
        old = parse_processes('501 10 1 100 0:10 01:00')
        _, previous = process_sample(old, [10], None, 0)
        new = parse_processes('501 10 1 100 1:10 02:00\n501 12 10 100 0:06 00:10')
        sample, _ = process_sample(new, [10], previous, 60)
        self.assertAlmostEqual(sample['app_cpu_percent'], 110)
        self.assertTrue(sample['app_cpu_complete'])

    def test_live_child_detachment_is_incomplete(self):
        old = parse_processes('501 10 1 100 0:10 01:00\n501 11 10 100 0:20 00:30')
        _, previous = process_sample(old, [10], None, 0)
        new = parse_processes('501 10 1 100 0:40 02:00\n501 11 1 100 0:40 01:30')
        sample, _ = process_sample(new, [10], previous, 60)
        self.assertFalse(sample['app_cpu_complete'])
        self.assertIsNone(sample['app_cpu_percent'])

    def test_host_cpu_uses_whole_interval_and_wraps_uint32(self):
        from zeekr_control.resource_monitor import host_cpu_delta
        self.assertEqual(host_cpu_delta((100, 100, 800, 0), (130, 130, 840, 0)), 60)
        self.assertEqual(host_cpu_delta((2**32-10, 0, 100, 0), (10, 0, 180, 0)), 20)
        with self.assertRaises(ValueError):
            host_cpu_delta((10, 10, 10, 10), (10, 10, 10, 10))

    def test_endpoint_failure_requires_its_own_three_observations(self):
        self.ticks(healthy(endpoints={'local': False, 'https': True}), count=2)
        self.sender.assert_not_called()
        self.monitor.tick(healthy(endpoints={'local': False, 'https': True}), 1120)
        self.assertIn('可用性', self.sender.call_args.args[0])
        self.assertIn('本机网页', self.sender.call_args.args[1])

    def test_watchdog_is_separate_from_primary_health_and_rate_limited(self):
        from zeekr_control.resource_monitor import observer_sample
        self.ticks(healthy())
        watchdog = ResourceHealth(self.monitor.root, self.sender, 'resource-watchdog.json')
        for now in (1400, 1401, 1460, 1520):
            watchdog.tick(observer_sample(self.monitor.root, now), now)
        self.assertEqual(self.sender.call_count, 1)
        self.assertIn('监测失效', self.sender.call_args.args[0])
        self.assertEqual(self.monitor.cached()['checked_at'], 1120)

    def test_legacy_alarm_migration_preserves_uncertain_delivery(self):
        self.monitor.save(dict(level='critical', reasons=['Zeekr 进程树内存持续超预算'],
                               notification_state='uncertain', checked_at=940,
                               sample=healthy(app_rss_bytes=2*1024**3)))
        self.ticks(healthy(app_rss_bytes=2*1024**3))
        self.sender.assert_not_called()
        self.assertEqual(self.monitor.cached()['level'], 'warning')

    def test_watchdog_runs_while_collection_paused_and_storage_check_fails(self):
        from zeekr_control.delivery_runtime import DeliveryWorker
        with patch('zeekr_control.delivery_runtime.observer_enabled', return_value=True):
            worker=DeliveryWorker(self.monitor.root/'session.json',sender=None,alert_sender=self.sender)
        worker.storage.tick=Mock(side_effect=OSError('synthetic'))
        with patch('zeekr_control.delivery_runtime.read_settings', return_value=(False,)), patch('builtins.print'):
            for now in (1000,1060,1120):worker.tick(now*1000)
        self.assertEqual(self.sender.call_count,1)
        self.assertEqual(worker.status,'paused')
        self.assertIn('心跳',self.sender.call_args.args[1])

    def test_http_probe_checks_auth_boundary_and_does_not_follow_redirects(self):
        import io
        import urllib.error
        from zeekr_control.resource_monitor import probe_origin
        opener=Mock();response=Mock();response.status=200
        response.__enter__=Mock(return_value=response);response.__exit__=Mock()
        denied=urllib.error.HTTPError('https://example.test/api/state',401,'synthetic',{},io.BytesIO())
        opener.open.side_effect=[response,denied]
        with patch('zeekr_control.resource_monitor.urllib.request.build_opener',return_value=opener) as build:
            self.assertTrue(probe_origin('https://example.test'))
        self.assertEqual(opener.open.call_args_list[1].args,('https://example.test/api/state',))
        self.assertEqual(build.call_args.args[0].proxies,{})
        self.assertIsNone(build.call_args.args[1].redirect_request(None,None,None,None,None))
        opener.open.side_effect=urllib.error.HTTPError('https://example.test/',302,'redirect',{},io.BytesIO())
        with patch('zeekr_control.resource_monitor.urllib.request.build_opener',return_value=opener):
            self.assertFalse(probe_origin('https://example.test'))

    def test_shutdown_after_durable_intent_does_not_start_network_send(self):
        self.ticks(healthy(host_cpu_percent=99),count=2)
        allowed=iter([True,False])
        self.monitor.tick(healthy(host_cpu_percent=99),1120,can_send=lambda:next(allowed))
        self.sender.assert_not_called()
        self.assertEqual(self.monitor.cached()['notification_state'],'pending')

    def test_stable_unknown_does_not_resend_after_restart_or_day(self):
        unavailable=healthy(memory_pressure=None,sample_errors=['memory_pressure'])
        self.sender.side_effect=DeliveryError('synthetic',ambiguous=True)
        self.ticks(unavailable)
        self.monitor=ResourceHealth(self.monitor.root,self.sender)
        self.ticks(unavailable,90000)
        self.assertEqual(self.sender.call_count,1)

    def test_host_recovery_does_not_clear_unknown_memory_pressure(self):
        self.ticks(healthy(host_cpu_percent=99,memory_pressure='critical'))
        self.ticks(healthy(memory_pressure=None,sample_errors=['memory_pressure']),1180)
        state=self.monitor.cached()
        self.assertEqual(state['conditions']['host_cpu']['level'],'healthy')
        self.assertEqual(state['conditions']['memory_pressure']['level'],'critical')
        self.assertIn('未证实恢复',self.sender.call_args.args[1])

