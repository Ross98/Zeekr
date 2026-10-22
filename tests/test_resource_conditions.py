"""Regression evidence for resource alarms; all notifications are synthetic."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from zeekr_control.notifications import DeliveryError
from zeekr_control.resource_monitor import ResourceHealth, NativeSampler, process_sample, parse_processes
from test_resource_monitor import healthy


class ConditionTests(unittest.TestCase):
    def test_host_and_process_resources_are_display_only_even_when_unknown(self):
        for sample in [healthy(host_cpu_percent=99, memory_pressure='critical',
                               app_cpu_percent=250, app_rss_bytes=2*1024**3),
                       healthy(host_cpu_percent=None, memory_pressure=None,
                               app_cpu_percent=None, app_cpu_complete=False,
                               sample_errors=['host_cpu', 'memory_pressure', 'processes'])]:
            self.ticks(sample)
            self.ticks(sample, 90000)
        self.sender.assert_not_called()
        self.assertEqual(self.monitor.cached()['level'], 'healthy')
        self.assertIsNone(self.monitor.cached()['sample']['memory_pressure'])

    def test_old_host_alarm_retires_silently_including_pending_retry(self):
        for delivery in ('sent', 'failed', 'pending', 'uncertain', 'sending'):
            self.monitor.save(dict(checked_at=940, level='warning', incident='memory_pressure=warning',
                notification_state=delivery, retry_at=0, attempt_at=900,
                conditions={'memory_pressure':dict(level='warning', observed='warning',
                    category='system', reason='old host pressure', streak=10)}, sample=healthy()))
            self.ticks(healthy(memory_pressure='warning'))
            self.ticks(healthy(), 90000)
            self.assertEqual(self.monitor.cached()['incident'], '')
            self.assertEqual(self.monitor.cached()['level'], 'healthy')
        self.sender.assert_not_called()

    def test_real_service_failure_still_alerts_despite_host_pressure_and_recovers(self):
        self.ticks(healthy(memory_pressure='critical', endpoints={'local':False,'https':True}))
        self.assertEqual(self.sender.call_count,1)
        title, body=self.sender.call_args.args
        self.assertIn('服务',title)
        self.assertNotIn('主机 CPU',body)
        self.assertNotIn('系统内存压力',body)
        self.ticks(healthy(memory_pressure='critical', endpoints={'local':True,'https':True}),1180)
        self.assertEqual(self.sender.call_count,2)
        self.assertIn('恢复',self.sender.call_args.args[0])

    def test_collection_pause_is_quiet_but_stale_enabled_collector_alerts(self):
        self.ticks(healthy(collection_health={'enabled':False,'online':False}))
        self.sender.assert_not_called()
        self.ticks(healthy(collection_health={'enabled':True,'online':False}),1180)
        self.assertEqual(self.sender.call_count,1)
        self.assertIn('采集',self.sender.call_args.args[1])

    def test_scope_migration_keeps_real_service_delivery_and_recovery(self):
        self.monitor.save(dict(checked_at=940,level='critical',
            incident='endpoint:local=critical|memory_pressure=warning',
            notification_state='sent',attempt_at=900,
            conditions={'memory_pressure':dict(level='warning',observed='warning',category='system',reason='old host pressure'),
                        'endpoint:local':dict(level='critical',observed='critical',category='availability',reason='local unavailable',streak=10)},sample=healthy()))
        self.ticks(healthy(endpoints={'local':False,'https':True},memory_pressure='warning'))
        self.sender.assert_not_called()
        self.assertEqual(self.monitor.cached()['incident'],'endpoint:local=critical')
        self.ticks(healthy(memory_pressure='warning'),1180)
        self.assertEqual(self.sender.call_count,1)
        self.assertIn('恢复',self.sender.call_args.args[0])
        self.assertNotIn('old host pressure',self.sender.call_args.args[1])

    def test_classification_reasons_only_describe_service_scope(self):
        from zeekr_control.resource_monitor import classify
        level,reasons=classify(healthy(host_cpu_percent=99,memory_pressure='critical',
                                      missing_services=['local.zeekr.web']))
        self.assertEqual(level,'critical')
        self.assertEqual(reasons,['local.zeekr.web 服务任务不可用'])

    def test_native_sampler_collection_reader_failure_is_unknown_not_healthy(self):
        def fail(*_):raise OSError('PRIVATE')
        sampler=NativeSampler(run=fail,host_reader=fail,probe=lambda _:True,
            origin_reader=lambda:'https://example.test',collection_reader=fail)
        sample=sampler.measure()
        self.assertIsNone(sample['collection_health'])
        self.assertNotIn('PRIVATE',str(sample))

    def test_cached_projection_is_private_stale_aware_and_reference_only(self):
        from zeekr_control.resource_monitor import resource_status
        self.monitor.save(dict(checked_at=1000, sample=healthy(memory_pressure='critical',
            host_cpu_percent=99, app_rss_bytes=0, private_token='PRIVATE', collector_pid=123),
            conditions={'memory_pressure':dict(level='critical')}, incident='memory_pressure=critical'))
        before=self.monitor.path.read_bytes()
        result=resource_status(self.monitor.root,now=1060)
        self.assertTrue(result['fresh'])
        self.assertEqual(result['host']['memory_pressure'],'critical')
        self.assertEqual(result['application']['rss_bytes'],0)
        self.assertEqual(result['alert_level'],'healthy')
        self.assertNotIn('PRIVATE',str(result));self.assertNotIn('123',str(result))
        self.assertEqual(before,self.monitor.path.read_bytes())
        self.assertFalse(resource_status(self.monitor.root,now=1300)['fresh'])
        self.assertFalse(resource_status(self.monitor.root,now=900)['fresh'])

    def test_collection_health_respects_pause_and_scheduled_backoff(self):
        from zeekr_control.resource_monitor import collection_health
        from zeekr_control.storage import save
        save(self.monitor.root/'monitor-health.json',dict(status='cooldown',heartbeat='1000000',next_check='1600000'))
        self.assertTrue(collection_health(self.monitor.root,1500)['online'])
        self.assertFalse(collection_health(self.monitor.root,1800)['online'])
        save(self.monitor.root/'sampling.json',dict(enabled='false'))
        self.assertFalse(collection_health(self.monitor.root,1800)['enabled'])

    def test_process_cpu_uses_actual_mach_timebase(self):
        from zeekr_control.resource_monitor import mach_seconds
        with patch('zeekr_control.resource_monitor.mach_timebase',return_value=(125,3)):
            self.assertEqual(mach_seconds(24000000),1)

    def test_process_inventory_rejects_membership_race(self):
        import os
        from zeekr_control.resource_monitor import process_inventory
        before='%d 10 1 100 0:01 00:10'%os.getuid()
        after=before+'\n%d 11 10 100 0:00 00:00'%os.getuid()
        run=Mock(side_effect=[before,after]);reader=Mock(return_value=(1.0,123))
        with self.assertRaises(ValueError):process_inventory([10],run,reader)

    def test_process_inventory_records_native_birth_and_cpu(self):
        import os
        from zeekr_control.resource_monitor import process_inventory
        rows='%d 10 1 100 0:01 00:10'%os.getuid()
        result=process_inventory([10],Mock(return_value=rows),Mock(return_value=(1.25,123456)))
        self.assertEqual(result[10]['cpu'],1.25)
        self.assertEqual(result[10]['start'],123456)

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

    def test_unrelated_partial_cpu_does_not_block_service_recovery(self):
        self.ticks(healthy(endpoints={'local':False,'https':True}))
        self.ticks(healthy(app_cpu_percent=None, app_cpu_complete=False),1180)
        self.assertEqual(self.monitor.cached()['level'],'healthy')
        self.assertIn('恢复',self.sender.call_args.args[0])

    def test_retry_never_reuses_a_reason_that_is_no_longer_observed(self):
        self.sender.side_effect=DeliveryError('synthetic',permanent=False)
        self.ticks(healthy(endpoints={'local':False,'https':True}))
        self.sender.side_effect=None
        self.ticks(healthy(missing_services=['local.zeekr.reports']),1180,16)
        messages=[' '.join(call.args) for call in self.sender.call_args_list[1:]]
        self.assertTrue(messages)
        self.assertNotIn('本机网页访问或认证边界异常',messages[-1].splitlines())
        self.assertIn('local.zeekr.reports',messages[-1])

    def test_large_app_alone_is_reference_not_push_incident(self):
        self.ticks(healthy(app_rss_bytes=2*1024**3, app_cpu_percent=250))
        self.assertEqual(self.monitor.cached()['level'],'healthy')
        self.assertEqual(self.monitor.cached()['conditions']['app_rss']['level'],'warning')
        self.sender.assert_not_called()

    def test_new_same_severity_reason_has_own_confirmation_and_notice(self):
        bad={'local':False,'https':True}
        self.ticks(healthy(endpoints=bad))
        both={'local':False,'https':False}
        self.ticks(healthy(endpoints=both),1180,2)
        self.assertEqual(self.sender.call_count,1)
        self.monitor.tick(healthy(endpoints=both),1300)
        self.assertEqual(self.sender.call_count,2)

    def test_unknown_collector_cannot_claim_recovery(self):
        self.ticks(healthy(collection_health={'enabled':True,'online':False}))
        self.ticks(healthy(collection_health=None),1180)
        self.assertEqual(self.monitor.cached()['conditions']['collector']['level'],'critical')
        self.assertIn('未证实恢复',self.sender.call_args.args[1])

    def test_reference_cpu_hysteresis_does_not_create_notifications(self):
        self.ticks(healthy(host_cpu_percent=96))
        self.ticks(healthy(host_cpu_percent=94),1180)
        self.assertEqual(self.monitor.cached()['conditions']['host_cpu']['level'],'critical')
        self.ticks(healthy(host_cpu_percent=88),1360)
        self.assertEqual(self.monitor.cached()['conditions']['host_cpu']['level'],'warning')
        self.sender.assert_not_called()

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
        self.assertIn('巡检失效', self.sender.call_args.args[0])
        self.assertEqual(self.monitor.cached()['checked_at'], 1120)

    def test_legacy_alarm_migration_preserves_uncertain_delivery(self):
        self.monitor.save(dict(level='critical', reasons=['Zeekr 进程树内存持续超预算'],
                               notification_state='uncertain', checked_at=940,
                               sample=healthy(app_rss_bytes=2*1024**3)))
        self.ticks(healthy(app_rss_bytes=2*1024**3))
        self.sender.assert_not_called()
        self.assertEqual(self.monitor.cached()['level'], 'healthy')

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
        self.ticks(healthy(endpoints={'local':False,'https':True}),count=2)
        allowed=iter([True,False])
        self.monitor.tick(healthy(endpoints={'local':False,'https':True}),1120,can_send=lambda:next(allowed))
        self.sender.assert_not_called()
        self.assertEqual(self.monitor.cached()['notification_state'],'pending')

    def test_stable_unknown_does_not_resend_after_restart_or_day(self):
        unavailable=healthy(collection_health=None)
        self.sender.side_effect=DeliveryError('synthetic',ambiguous=True)
        self.ticks(unavailable)
        self.monitor=ResourceHealth(self.monitor.root,self.sender)
        self.ticks(unavailable,90000)
        self.assertEqual(self.sender.call_count,1)

    def test_host_reference_change_never_blocks_collector_recovery(self):
        self.ticks(healthy(host_cpu_percent=99,collection_health={'enabled':True,'online':False}))
        self.ticks(healthy(memory_pressure=None,sample_errors=['memory_pressure']),1180)
        self.assertEqual(self.monitor.cached()['level'],'healthy')
        self.assertIn('恢复',self.sender.call_args.args[0])
