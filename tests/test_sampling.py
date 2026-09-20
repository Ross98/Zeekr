"""Unified collection uses synthetic data only."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zeekr_control.storage import save, load
from zeekr_control.monitor_runtime import Runner
from zeekr_control.web import App
from test_monitor import BASE, sample

class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private'
        self.session = self.root / 'session.json'
        save(self.session, {'accessToken': 'synthetic'})
        class Client:
            raw = sample(0)
            calls = 0
            def __init__(self, session): pass
            def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
            def status(self, vin):
                Client.calls += 1
                return Client.raw
        self.client = Client
        self.runner = Runner(self.session, client_factory=Client, sender=lambda _: None)

    def tick(self, t, **kwargs):
        self.client.raw = sample(t, **kwargs)
        return self.runner.tick(BASE + t * 1000)

    def test_parked_ten_minutes_and_drive_keep_thirty_seconds(self):
        for t in range(0, 600, 60):
            self.assertEqual(self.tick(t), 30)
        self.assertEqual(self.tick(600), 30)
        self.assertEqual(self.tick(900), 30)
        self.assertEqual(self.tick(1200, speed=30, engine='engine_on', ready=1, km=101), 30)

    def test_stale_stationary_does_not_confirm_parking(self):
        self.runner.tick(BASE)
        self.assertEqual(self.runner.tick(BASE + 600000), 30)

    def test_charging_or_unknown_power_never_slows(self):
        for params in ({'code':'charging', 'dc_lid':1}, {'engine':'unknown'}):
            for t in range(0, 1200, 60):
                self.assertEqual(self.tick(t, **params), 30)

    def test_web_pause_stops_runner_queries_and_resume_works(self):
        app = App(self.session, client_factory=self.client)
        self.addCleanup(app.close)
        app.recording(False, 60)
        self.runner.tick(BASE)
        self.assertEqual(self.client.calls, 0)
        app.recording(True, 60)
        self.runner.tick(BASE + 60000)
        self.assertEqual(self.client.calls, 1)
        self.assertEqual(app.state()['recording']['interval'], 60)

    def test_idle_points_recorded_and_duplicate_cache_not_added(self):
        self.tick(0)
        self.runner.tick(BASE + 1000)
        with self.runner.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 1)

    def test_web_has_no_independent_sampling_worker(self):
        app = App(self.session, client_factory=self.client)
        self.addCleanup(app.close)
        self.assertFalse(hasattr(app, 'worker'))
        app.refresh(1)
        self.assertEqual(self.client.calls, 1)
        with self.runner.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 0)

    def test_new_backend_start_enables_sampling(self):
        from zeekr_control.monitor_runtime import enable_sampling
        save(self.root / 'sampling.json', {'enabled':'false', 'interval':'10'})
        enable_sampling(self.root)
        self.assertEqual(load(self.root / 'sampling.json')['enabled'], 'true')
        self.assertEqual(load(self.root / 'sampling.json')['interval'], '10')

    def test_stationary_position_with_power_on_stays_fast(self):
        for t in range(0, 1200, 60):
            self.assertEqual(self.tick(t, engine='engine_on', ready=1), 30)

    def test_confirmed_parking_and_replayed_cache_keep_thirty_seconds(self):
        for t in range(0, 601, 60):
            self.tick(t)
        self.assertEqual(self.runner.tick(BASE + 1200000), 30)

    def test_trip_end_confirmation_still_requires_ten_minutes(self):
        self.tick(0, speed=30, engine='engine_on', ready=1)
        for t in range(60, 660, 60):
            self.assertEqual(self.tick(t), 30)
        self.assertEqual(self.tick(660), 30)
        self.assertEqual([e['kind'] for e in self.runner.monitor.events()], ['trip_end'])

    def test_web_fallback_does_not_create_runner_when_owner_exists(self):
        from zeekr_control.monitor_runtime import background, process_lock
        import threading
        stop = threading.Event()
        with process_lock(self.root / 'monitor.lock'), patch('zeekr_control.monitor_runtime.Runner') as factory:
            with patch.object(stop, 'wait', side_effect=lambda _: stop.set()):
                background(self.session, stop)
            factory.assert_not_called()

    def test_web_restart_reenables_shared_sampling(self):
        app = App(self.session, client_factory=self.client)
        self.addCleanup(app.close)
        app.recording(False, 60)
        with patch('zeekr_control.monitor_runtime.background') as background:
            app.start_monitor()
            app.monitor_thread.join(1)
        self.assertEqual(load(self.root / 'sampling.json')['enabled'], 'true')
        background.assert_called_once()

    def test_standalone_waits_for_web_owner_without_second_runner(self):
        from zeekr_control.monitor_runtime import run, process_lock
        with process_lock(self.root / 'monitor.lock'), patch('zeekr_control.monitor_runtime.Runner') as factory:
            import threading
            stop = threading.Event()
            with patch('zeekr_control.monitor_runtime.threading.Event', return_value=stop), patch.object(stop, 'wait', side_effect=lambda _: stop.set()):
                self.assertEqual(run(self.session), 0)
            factory.assert_not_called()

    def test_loop_notices_pause_and_resume_without_waiting_five_minutes(self):
        from zeekr_control.monitor_runtime import collection_loop
        import threading
        stop = threading.Event()
        calls = []
        def tick():
            calls.append(load(self.root / 'sampling.json').get('enabled', 'true'))
            return 300
        def wait(_):
            if len(calls) == 1:
                save(self.root / 'sampling.json', {'enabled':'false'})
            elif len(calls) == 2:
                save(self.root / 'sampling.json', {'enabled':'true'})
            else:
                stop.set()
        with patch.object(self.runner, 'tick', side_effect=tick), patch.object(stop, 'wait', side_effect=wait):
            collection_loop(self.runner, stop)
        self.assertEqual(calls, ['true', 'false', 'true'])

    def test_storage_check_continues_while_vehicle_sampling_paused(self):
        from zeekr_control.monitor_runtime import collection_loop
        import threading
        save(self.root/'sampling.json', {'enabled':'false'})
        with patch.object(self.runner.storage_health, 'tick') as health:
            collection_loop(self.runner, threading.Event(), once=True)
        health.assert_called_once()
        self.assertEqual(self.client.calls, 0)

    def test_configured_interval_and_pause_resume_survive_restart(self):
        app = App(self.session, client_factory=self.client)
        self.addCleanup(app.close)
        for interval in (10, 15, 30, 60):
            app.recording(True, interval)
            self.assertEqual(self.tick(interval), interval)
            self.assertEqual(self.runner.health()['interval'], str(interval))
            app.recording(False)
            self.assertEqual(app.state()['recording']['interval'], interval)
            from zeekr_control.monitor_runtime import enable_sampling
            enable_sampling(self.root)
            self.assertEqual(app.state()['recording']['interval'], interval)

    def test_web_and_monitor_query_policies_use_the_configured_profile(self):
        app = App(self.session)
        self.addCleanup(app.close)
        runner = Runner(self.session, sender=lambda _: None)
        save(self.root / 'sampling.json', {'interval':'10'})
        clients = [app.client_factory({}), runner.client_factory({})]
        calls = []
        for client in clients:
            self.assertEqual(client.query_policy.path, self.root / 'queries.sqlite3')
            client.query_policy.clock = lambda: 1000
            client.query_policy.run('synthetic', 'session', 'status', 'car', lambda: calls.append('request') or {})
            self.assertEqual(client.query_policy.next_query_at, 1010)
        self.assertEqual(calls, ['request'])

    def test_local_query_cooldown_retries_without_blocking_session(self):
        from zeekr_control.errors import ApiError
        with patch.object(self.client, 'status', side_effect=ApiError('本机查询保护', retry_after=12)):
            self.assertEqual(self.tick(0), 30)
        self.assertIsNone(self.runner.blocked_fingerprint)
        self.assertEqual(self.runner.health()['status'], 'cooldown')
        self.tick(30)
        self.assertEqual(self.client.calls, 1)

    def test_rate_limit_and_network_backoff_do_not_shrink_with_setting(self):
        from zeekr_control.errors import ApiError, RateLimited
        save(self.root / 'sampling.json', {'interval':'10'})
        with patch.object(self.client, 'status', side_effect=RateLimited(120)):
            self.assertEqual(self.tick(0), 120)
        self.assertEqual(self.runner.health()['interval'], '120')
        with patch.object(self.client, 'status', side_effect=ApiError('网络或 TLS 错误')):
            self.assertEqual(self.tick(120), 120)
            self.assertEqual(self.tick(240), 240)

    def test_loop_reschedules_normal_wait_but_preserves_backoff(self):
        from zeekr_control.monitor_runtime import collection_loop
        import threading
        for returned_delay, status, expected in ((30, 'fresh', [0, 10]), (120, 'retrying', [0, 120]), (30, 'cooldown', [0, 30])):
            save(self.root / 'sampling.json', {'interval':'30'})
            save(self.root / 'monitor-health.json', {'status': status})
            stop = threading.Event()
            clock, calls = [0], []
            def tick():
                calls.append(clock[0])
                if len(calls) == 2:
                    stop.set()
                return returned_delay
            def wait(_):
                clock[0] += 1
                if clock[0] == 5:
                    save(self.root / 'sampling.json', {'interval':'10'})
                if clock[0] > 121:
                    stop.set()
            with patch.object(self.runner, 'tick', side_effect=tick), patch.object(stop, 'wait', side_effect=wait), patch('zeekr_control.monitor_runtime.time.monotonic', side_effect=lambda: clock[0]), patch.object(self.runner.storage_health, 'tick'):
                collection_loop(self.runner, stop)
            self.assertEqual(calls, expected)
