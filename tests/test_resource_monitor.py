"""Resource alarms use synthetic observations and senders; no real Bark traffic."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from zeekr_control.notifications import DeliveryError
from zeekr_control.resource_monitor import ResourceHealth, cpu_seconds, parse_processes, process_sample, classify


def healthy(**changes):
    sample=dict(host_cpu_percent=10, memory_pressure='normal', app_cpu_percent=5,
                app_cpu_complete=True, app_rss_bytes=60*1024**2, process_count=4,
                missing_services=[], sample_errors=[], endpoints={'local':True,'https':True},
                collection_health={'enabled':True,'online':True})
    sample.update(changes);return sample


class ResourceTests(unittest.TestCase):
    def test_sampling_elapsed_moves_delivery_time_without_shifting_confirmation(self):
        high=healthy(endpoints={'local':False,'https':True});elapsed=[0.0]
        with patch('zeekr_control.resource_monitor.time.monotonic',side_effect=lambda:elapsed[0]):
            self.ticks(high,count=2)
            elapsed[0]=40.0
            def fail(*args):elapsed[0]+=20.0;raise DeliveryError('synthetic rejection')
            self.sender.side_effect=fail
            result=self.monitor.tick(high,now=1120,started=0.0)
        self.assertEqual(result['checked_at'],1120)
        self.assertEqual(result['level'],'critical')
        self.assertEqual(result['attempt_at'],1160)
        self.assertEqual(result['retry_at'],2080)

    def test_native_loop_passes_anchor_from_before_sampling(self):
        import threading
        from contextlib import nullcontext
        from zeekr_control.resource_monitor import main
        elapsed=[0.0];stop=threading.Event();monitor=Mock();sampler=Mock()
        def sample():elapsed[0]=40.0;return {'synthetic':True}
        sampler.measure.side_effect=sample
        monitor.tick.side_effect=lambda *args,**kwargs:stop.set()
        with patch('zeekr_control.resource_monitor.ResourceHealth',return_value=monitor),\
             patch('zeekr_control.resource_monitor.NativeSampler',return_value=sampler),\
             patch('zeekr_control.resource_monitor.BarkSender'),\
             patch('zeekr_control.resource_monitor.threading.Event',return_value=stop),\
             patch('zeekr_control.resource_monitor.signal.signal'),\
             patch('zeekr_control.resource_monitor.delivery_lock',return_value=nullcontext()),\
             patch('zeekr_control.resource_monitor.sys.platform','darwin'),\
             patch('zeekr_control.resource_monitor.time.time',return_value=1120),\
             patch('zeekr_control.resource_monitor.time.monotonic',side_effect=lambda:elapsed[0]):
            main(['--root',str(self.root)])
        self.assertEqual(monitor.tick.call_args.args,({'synthetic':True},))
        self.assertEqual(monitor.tick.call_args.kwargs['now'],1120)
        self.assertEqual(monitor.tick.call_args.kwargs['started'],0.0)

    def test_slow_permanent_failure_waits_hour_from_return(self):
        high=healthy(endpoints={'local':False,'https':True});elapsed=[0.0]
        with patch('zeekr_control.resource_monitor.time.monotonic',side_effect=lambda:elapsed[0]):
            self.ticks(high,count=2)
            def fail(*args):elapsed[0]+=20.0;raise DeliveryError('synthetic permanent',permanent=True)
            self.sender.side_effect=fail
            result=self.monitor.tick(high,now=1120)
            self.assertEqual(result['retry_at'],4740)
            elapsed[0]=3600.0
            self.monitor.tick(high,now=4720)
            self.sender.assert_called_once()

    def test_slow_send_failure_waits_full_backoff_after_completion(self):
        high=healthy(endpoints={'local':False,'https':True})
        elapsed=[0.0]
        with patch('zeekr_control.resource_monitor.time.monotonic',side_effect=lambda:elapsed[0]):
            self.ticks(high,count=2)
            def fail(*args):
                elapsed[0]+=20.0
                raise DeliveryError('synthetic slow rejection')
            self.sender.side_effect=fail
            result=self.monitor.tick(high,now=1120)
            self.assertEqual(result['retry_at'],2040)
            elapsed[0]=900.0
            self.monitor.tick(high,now=2020)
            self.sender.assert_called_once()

    def test_slow_message_failure_waits_full_backoff_after_preparation(self):
        high=healthy(endpoints={'local':False,'https':True});elapsed=[0.0]
        with patch('zeekr_control.resource_monitor.time.monotonic',side_effect=lambda:elapsed[0]):
            self.ticks(high,count=2)
            def prepare(*args):elapsed[0]+=20.0;raise ValueError('synthetic preparation')
            with patch.object(self.monitor,'message',side_effect=prepare):
                result=self.monitor.tick(high,now=1120)
            self.assertEqual(result['retry_at'],2040)
            self.sender.assert_not_called()

    def test_message_preparation_interruption_keeps_known_unsent_pending(self):
        high=healthy(endpoints={'local':False,'https':True})
        self.ticks(high,count=2)
        with patch.object(self.monitor,'message',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.monitor.tick(high,now=1120)
        self.assertEqual(self.state()['notification_state'],'pending')
        self.sender.assert_not_called()
        self.monitor=ResourceHealth(self.root,self.sender)
        self.monitor.tick(high,now=1180)
        self.sender.assert_called_once()
        self.assertEqual(self.state()['notification_state'],'sent')

    def test_message_preparation_error_is_failed_without_claiming_send(self):
        high=healthy(endpoints={'local':False,'https':True})
        self.ticks(high,count=2)
        with patch.object(self.monitor,'message',side_effect=ValueError('PRIVATE_SYNTHETIC')):
            self.monitor.tick(high,now=1120)
        self.assertEqual(self.state()['notification_state'],'failed')
        self.assertNotIn('attempt_at',self.state())
        self.sender.assert_not_called()
        self.assertNotIn('PRIVATE_SYNTHETIC',self.monitor.path.read_text())
        self.monitor.tick(high,now=1180)
        self.sender.assert_not_called()
        self.monitor=ResourceHealth(self.root,self.sender)
        self.monitor.tick(high,now=2020)
        self.sender.assert_called_once()
        self.assertEqual(self.state()['notification_state'],'sent')

    def test_final_guard_checks_after_message_preparation(self):
        high=healthy(endpoints={'local':False,'https':True});self.ticks(high,count=2)
        allowed=[True]
        def prepare(state):allowed[0]=False;return ('title','body')
        with patch.object(self.monitor,'message',side_effect=prepare):
            self.monitor.tick(high,now=1120,can_send=lambda:allowed[0])
        self.sender.assert_not_called()
        self.assertEqual(self.state()['notification_state'],'pending')

    def test_raised_final_guard_does_not_leave_sending_intent(self):
        high=healthy(endpoints={'local':False,'https':True});self.ticks(high,count=2)
        guard=Mock(side_effect=[True,ValueError('synthetic cancellation')])
        with self.assertRaises(ValueError):self.monitor.tick(high,now=1120,can_send=guard)
        self.sender.assert_not_called()
        self.assertEqual(self.state()['notification_state'],'pending')
        self.monitor=ResourceHealth(self.root,self.sender)
        self.monitor.tick(high,now=1180)
        self.sender.assert_called_once()

    def test_actual_sender_interruption_remains_uncertain_after_restart(self):
        high=healthy(endpoints={'local':False,'https':True});self.ticks(high,count=2)
        self.sender.side_effect=KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):self.monitor.tick(high,now=1120)
        self.assertEqual(self.state()['notification_state'],'sending')
        self.monitor=ResourceHealth(self.root,self.sender)
        self.sender.side_effect=None
        self.monitor.tick(high,now=1180)
        self.monitor.tick(high,now=90000)
        self.sender.assert_called_once()
        self.assertEqual(self.state()['notification_state'],'uncertain')

    def setUp(self):
        clock_patch=patch('zeekr_control.resource_monitor.time.monotonic',return_value=0.0)
        clock_patch.start();self.addCleanup(clock_patch.stop)
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.sender=Mock()
        self.monitor=ResourceHealth(self.root,self.sender)

    def ticks(self,sample,start=1000,count=3):
        for i in range(count):self.monitor.tick(sample,now=start+i*60)

    def state(self):return json.loads(json.loads((self.root/'resource-health.json').read_text())['state'])

    def test_first_healthy_observations_stay_quiet(self):
        self.ticks(healthy());self.sender.assert_not_called()
        self.assertEqual(self.state()['level'],'healthy')

    def test_sustained_service_alert_and_confirmed_recovery(self):
        high=healthy(endpoints={'local':False,'https':True})
        self.ticks(high,count=2);self.sender.assert_not_called()
        self.monitor.tick(high,now=1120);self.assertEqual(self.sender.call_count,1)
        self.assertEqual(self.state()['notification_state'],'sent')
        self.ticks(high,start=1180);self.assertEqual(self.sender.call_count,1)
        self.ticks(healthy(),start=1360);self.assertEqual(self.sender.call_count,2)
        self.assertIn('恢复',self.sender.call_args.args[0])

    def test_rapid_repeats_and_long_gap_do_not_fake_persistence(self):
        high=healthy(endpoints={'local':False,'https':True})
        for t in (1000,1001,1002,2000,2060):self.monitor.tick(high,now=t)
        self.sender.assert_not_called()
        self.monitor.tick(high,now=2120);self.assertEqual(self.sender.call_count,1)

    def test_restart_keeps_streak_but_does_not_resend_confirmed_alert(self):
        high=healthy(endpoints={'local':False,'https':True})
        self.ticks(high,count=2)
        self.monitor=ResourceHealth(self.root,self.sender);self.monitor.tick(high,now=1120)
        self.assertEqual(self.sender.call_count,1)
        self.monitor=ResourceHealth(self.root,self.sender);self.monitor.tick(high,now=1180)
        self.assertEqual(self.sender.call_count,1)

    def test_ambiguous_send_and_interrupted_intent_never_auto_retry(self):
        self.sender.side_effect=DeliveryError('synthetic',ambiguous=True)
        high=healthy(endpoints={'local':False,'https':True})
        self.ticks(high);self.assertEqual(self.state()['notification_state'],'uncertain')
        self.monitor=ResourceHealth(self.root,self.sender)
        self.ticks(high,start=1180);self.ticks(high,start=90000)
        self.assertEqual(self.sender.call_count,1)
        state=self.state();state['notification_state']='sending';self.monitor.save(state)
        self.monitor=ResourceHealth(self.root,self.sender);self.monitor.tick(high,now=90200)
        self.assertEqual(self.state()['notification_state'],'uncertain')
        self.assertEqual(self.sender.call_count,1)

    def test_definite_failure_retries_after_delay_without_relabeling_success(self):
        self.sender.side_effect=DeliveryError('rejected',permanent=False)
        high=healthy(endpoints={'local':False,'https':True});self.ticks(high)
        self.assertEqual(self.state()['notification_state'],'failed')
        self.monitor.tick(high,now=1180);self.assertEqual(self.sender.call_count,1)
        self.sender.side_effect=None;self.monitor.tick(high,now=2020)
        self.assertEqual(self.sender.call_count,2)
        self.assertEqual(self.state()['notification_state'],'sent')

    def test_failed_intent_save_prevents_network_send(self):
        high=healthy(endpoints={'local':False,'https':True});self.ticks(high,count=2)
        with patch.object(self.monitor,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.monitor.tick(high,now=1120)
        self.sender.assert_not_called()

    def test_sampling_failure_does_not_clear_alarm_or_turn_into_zero(self):
        self.assertEqual(classify(healthy(memory_pressure=None,sample_errors=['memory_pressure']))[0],'healthy')
        self.assertEqual(classify(healthy(app_cpu_percent=None,app_cpu_complete=False))[0],'healthy')
        self.assertEqual(classify(healthy(memory_pressure='critical'))[0],'healthy')
        self.assertEqual(classify(healthy(missing_services=['local.zeekr.web']))[0],'critical')

    def test_process_tree_includes_detached_children_and_excludes_other_apps(self):
        rows=parse_processes('501 10 1 100 0:01.00 00:20\n501 11 10 200 0:02.50 00:10\n501 99 1 900 0:50.00 01:00\n')
        sample,counters=process_sample(rows,[10],None,60)
        self.assertEqual(sample['app_rss_bytes'],300*1024)
        self.assertEqual(sample['process_count'],2)
        self.assertIsNone(sample['app_cpu_percent'])
        new=parse_processes('501 10 1 100 0:31.00 01:20\n501 11 10 200 0:32.50 01:10\n')
        sample,_=process_sample(new,[10],counters,60)
        self.assertAlmostEqual(sample['app_cpu_percent'],100)
        self.assertTrue(sample['app_cpu_complete'])
        reused=parse_processes('501 10 1 100 0:40.00 00:05\n')
        sample,_=process_sample(reused,[10],counters,60)
        self.assertFalse(sample['app_cpu_complete'])
        self.assertIsNone(sample['app_cpu_percent'])

    def test_cpu_clock_parsing_and_malformed_process_data(self):
        self.assertEqual(cpu_seconds('2-01:02:03.5'),176523.5)
        self.assertEqual(cpu_seconds('154:36.93'),9276.93)
        with self.assertRaises(ValueError):parse_processes('malformed')

    def test_confirmed_daily_reminder_and_short_spike_recovery(self):
        high=healthy(endpoints={'local':False,'https':True})
        self.ticks(high,count=1);self.ticks(healthy(),start=1060)
        self.sender.assert_not_called()
        self.ticks(high,start=1240);self.assertEqual(self.sender.call_count,1)
        self.ticks(high,start=88000);self.assertEqual(self.sender.call_count,2)

    def test_native_sampler_uses_pressure_export_flags_and_bounds_unknown(self):
        import os
        from zeekr_control.resource_monitor import NativeSampler
        def command(argv):
            if argv[0].endswith('top'):return 'CPU usage: 1% user, 2% sys, 97% idle\nCPU usage: 10% user, 20% sys, 70% idle\n'
            if argv[0].endswith('sysctl'):return '2\n'
            if argv[0].endswith('launchctl'):
                pid={'web':10,'monitor':20,'reports':30}[argv[-1].split('.')[-1]]
                return '\tstate = running\n\tpid = %d\n'%pid
            return '\n'.join('%d %d 1 100 0:01.00 00:20'%(os.getuid(),pid) for pid in (10,20,30))
        ticks=iter([(100,100,800,0),(130,130,940,0)])
        sampler=NativeSampler(command,host_reader=lambda:next(ticks),probe=lambda origin:True,origin_reader=lambda:'https://example.test',usage_reader=lambda pid:(1.0,pid))
        sample=sampler.measure()
        self.assertIsNone(sample['host_cpu_percent'])
        with patch('zeekr_control.resource_monitor.time.monotonic',return_value=sampler.host_checked+60):
            measured=sampler.measure()
        self.assertEqual(measured['host_cpu_percent'],30)
        self.assertEqual(sample['memory_pressure'],'warning')
        self.assertEqual(sample['missing_services'],[])
        self.assertEqual(sample['sample_errors'],[])
        self.assertEqual(sample['app_rss_bytes'],300*1024)
        self.assertIsNone(sample['app_cpu_percent'])
        def failed(argv):raise OSError('synthetic private details')
        def failed_host():raise OSError('synthetic private details')
        sample=NativeSampler(failed,host_reader=failed_host,probe=lambda origin:False,origin_reader=lambda:'https://example.test').measure()
        self.assertIsNone(sample['host_cpu_percent']);self.assertIsNone(sample['memory_pressure'])
        self.assertTrue(sample['sample_errors'])
        self.assertNotIn('synthetic private details',json.dumps(sample))

    def test_restart_inside_sample_interval_refreshes_identity_without_extra_observation(self):
        first=healthy(collector_pid=111)
        self.monitor.tick(first,now=1000)
        self.monitor=ResourceHealth(self.root,self.sender)
        self.monitor.tick(healthy(collector_pid=222),now=1005)
        state=self.state()
        self.assertEqual(state['monitor_pid'],222)
        self.assertEqual(state['checked_at'],1000)
        self.assertEqual(state['streak'],1)
        self.sender.assert_not_called()
