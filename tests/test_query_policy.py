"""Offline tests: identifiers and observations are synthetic, never owner records."""
import multiprocessing
from pathlib import Path
import tempfile
import time
import unittest

from zeekr_control.query_policy import QueryPolicy, retry_seconds
from zeekr_control.errors import ApiError, RateLimited
from zeekr_control.storage import save


def competing_reader(path, events, start):
    policy = QueryPolicy(path)
    start.wait(5)
    def fetch():
        events.put('start')
        time.sleep(0.15)
        events.put('end')
        return {'data': 48}
    result = policy.run('account', 'session', 'status', 'car', fetch)
    events.put(('result', result))


def crashing_status_reader(path):
    import os
    policy=QueryPolicy(path,clock=lambda:1000.0)
    policy.run('account','session','status','car',lambda:os._exit(73))


class QueryPolicyTests(unittest.TestCase):
    def test_unrepresentable_retry_after_uses_existing_fallback(self):
        for value in ('9'*400,'1'+'0'*306):
            with self.subTest(digits=len(value)):
                self.assertEqual(retry_seconds(value,now=1000),60)
        self.assertEqual(retry_seconds(str(10**20),now=1000),10**20)

    def test_http_429_with_unrepresentable_header_still_blocks_other_operations(self):
        from unittest.mock import Mock,patch
        from urllib.error import HTTPError
        from zeekr_control.client import Client
        opener=Mock()
        opener.open.side_effect=HTTPError('https://example.invalid',429,'synthetic',{'Retry-After':'9'*400},None)
        client=Client({'accessToken':'synthetic-access','userId':'synthetic-user'},query_policy=self.policy)
        with patch('zeekr_control.client.build_opener',return_value=opener):
            with self.assertRaises(RateLimited) as caught:client.vehicles()
        self.assertEqual(caught.exception.seconds,60)
        fetch=Mock(return_value={'accepted':True})
        self.now+=59
        with self.assertRaises(ApiError) as deferred:
            self.policy.run('other-account','other-session','sms','',fetch)
        self.assertEqual(deferred.exception.retry_after,1)
        fetch.assert_not_called()
        self.now+=1
        self.assertEqual(self.policy.run('other-account','other-session','sms','',fetch),{'accepted':True})
        opener.open.assert_called_once()
        fetch.assert_called_once()

    def test_process_exit_during_transport_preserves_status_interval(self):
        worker=multiprocessing.get_context('spawn').Process(target=crashing_status_reader,args=(self.path,))
        worker.start();worker.join(5)
        if worker.is_alive():worker.terminate();worker.join()
        self.assertEqual(worker.exitcode,73)
        with self.assertRaises(ApiError):self.run_query(session='replacement-session')
        self.assertEqual(self.calls,0)
        self.now+=30
        self.assertEqual(self.run_query(session='replacement-session')['data']['value'],1)

    def test_keyboard_interrupt_and_system_exit_preserve_status_reservation(self):
        from unittest.mock import Mock
        for error in (KeyboardInterrupt,SystemExit):
            with self.subTest(error=error.__name__):
                policy=QueryPolicy(self.path.with_name(error.__name__+'.sqlite3'),clock=lambda:1000.0)
                with self.assertRaises(error):policy.run('account','session','status','car',Mock(side_effect=error))
                fetch=Mock(return_value={})
                with self.assertRaises(ApiError):policy.run('account','new-session','status','other-car',fetch)
                fetch.assert_not_called()

    def checkpoint_policy(self,hook):
        import sqlite3
        class CheckpointConnection(sqlite3.Connection):
            def commit(connection):
                super().commit()
                if not getattr(connection,'checkpointed',False):
                    connection.checkpointed=True;hook()
        def connect():
            db=sqlite3.connect(self.path,timeout=25,isolation_level=None,factory=CheckpointConnection)
            self.path.chmod(0o600)
            return db
        return connect

    def test_gateway_cooldown_from_legacy_caller_between_transactions_is_honored(self):
        import sqlite3
        from unittest.mock import Mock,patch
        def legacy():
            with sqlite3.connect(self.path) as db:db.execute("INSERT OR REPLACE INTO cooldown VALUES('gateway',1120)")
        fetch=Mock(return_value={})
        with patch.object(self.policy,'_connect',side_effect=self.checkpoint_policy(legacy)):
            with self.assertRaises(ApiError) as caught:self.policy.run('account','session','status','car',fetch)
        self.assertEqual(caught.exception.retry_after,120)
        self.assertEqual(self.policy.next_query_at,1120)
        fetch.assert_not_called()

    def test_newer_legacy_status_reservation_is_not_overwritten_or_replayed(self):
        import sqlite3
        from unittest.mock import Mock,patch
        from zeekr_control.query_policy import digest
        def legacy():
            self.now=1010.0
            with sqlite3.connect(self.path) as db:
                db.execute('UPDATE status_attempts SET attempted=1010')
                db.execute('UPDATE cooldown SET until=1040 WHERE key=?',('status:'+digest('account'),))
        fetch=Mock(return_value={})
        with patch.object(self.policy,'_connect',side_effect=self.checkpoint_policy(legacy)):
            with self.assertRaises(ApiError) as caught:self.policy.run('account','session','status','car',fetch)
        self.assertEqual(caught.exception.retry_after,30)
        fetch.assert_not_called()
        with sqlite3.connect(self.path) as db:self.assertEqual(db.execute('SELECT attempted FROM status_attempts').fetchone()[0],1010)

    def test_fetch_delivery_busy_is_not_mistaken_for_query_lock_contention(self):
        from unittest.mock import Mock
        from zeekr_control.delivery_state import DeliveryBusy
        fetch=Mock(side_effect=DeliveryBusy('synthetic callback failure'))
        with self.assertRaises(DeliveryBusy):self.policy.run('account','session','status','car',fetch)
        fetch.assert_called_once()

    def test_query_file_lock_timeout_never_enters_transport(self):
        from unittest.mock import Mock,patch
        from zeekr_control.delivery_state import DeliveryBusy
        fetch=Mock(return_value={})
        with patch('zeekr_control.query_policy.delivery_lock',side_effect=DeliveryBusy()),\
             patch('zeekr_control.query_policy.time.monotonic',side_effect=[0.0,25.0]):
            with self.assertRaises(ApiError):self.policy.run('account','session','status','car',fetch)
        fetch.assert_not_called()

    def test_hardlinked_cache_cannot_mutate_another_database_or_reach_transport(self):
        import os
        import sqlite3
        target=self.path.parent/'unrelated.sqlite3'
        with sqlite3.connect(target) as db:
            db.execute('CREATE TABLE cache(key TEXT PRIMARY KEY,fetched REAL,expires REAL,data TEXT)')
            db.execute("INSERT INTO cache VALUES('unrelated',0,0,'preserve')")
        target.chmod(0o600)
        os.link(target,self.path)
        before=target.read_bytes()
        with self.assertRaises(ApiError):self.run_query()
        self.assertEqual(self.calls,0)
        self.assertEqual(target.read_bytes(),before)

    def test_uncacheable_response_keeps_status_attempt_and_is_retryable(self):
        import sqlite3
        from zeekr_control.errors import RequestDeferred
        def malformed():
            self.calls+=1
            return {'reading':float('nan')}
        with self.assertRaises(ApiError) as caught:
            self.policy.run('account','session','status','car',malformed)
        with self.assertRaises(RequestDeferred):
            self.run_query(session='new-session')
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(self.calls,1)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cache').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT attempted FROM status_attempts').fetchone()[0],self.now)
        self.now+=30
        self.assertEqual(self.run_query()['data']['value'],2)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'queries.sqlite3'
        self.now = 1000.0
        self.policy = QueryPolicy(self.path, clock=lambda: self.now)
        self.calls = 0

    def tearDown(self):
        self.temp.cleanup()

    def fetch(self):
        self.calls += 1
        return {'data': {'value': self.calls}}

    def run_query(self, operation='status', key='car', session='session'):
        return self.policy.run('account', session, operation, key, self.fetch)

    def test_independent_clients_share_cache_until_30_seconds(self):
        first = self.run_query()
        other = QueryPolicy(self.path, clock=lambda: self.now)
        self.now += 29
        self.assertEqual(other.run('account', 'session', 'status', 'car', self.fetch), first)
        self.assertEqual(self.calls, 1)
        self.now += 1
        self.assertEqual(self.run_query()['data']['value'], 2)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_different_vehicle_and_new_session_cannot_bypass_interval(self):
        self.run_query()
        for key, session in [('other-car', 'session'), ('car', 'new-session')]:
            with self.assertRaises(ApiError):
                self.run_query(key=key, session=session)
        self.assertEqual(self.calls, 1)
        self.now += 30
        self.assertEqual(self.run_query(session='new-session')['data']['value'], 2)

    def test_failed_query_still_throttles_next_attempt(self):
        def fail():
            raise ApiError('failure')
        with self.assertRaises(ApiError):
            self.policy.run('account', 'session', 'status', 'car', fail)
        with self.assertRaises(ApiError):
            self.run_query()
        self.assertEqual(self.calls, 0)

    def test_429_blocks_other_operations_across_instances(self):
        def limited():
            raise RateLimited(120)
        with self.assertRaises(RateLimited):
            self.policy.run('account', 'session', 'status', 'car', limited)
        other = QueryPolicy(self.path, clock=lambda: self.now)
        for operation in ('vehicles', 'sms', 'line_login'):
            with self.assertRaises(ApiError):
                other.run('account', 'session', operation, '', self.fetch)
        self.assertEqual(self.calls, 0)
        self.now += 120
        self.assertEqual(self.run_query()['data']['value'], 1)

    def test_successful_list_queries_also_share_cache(self):
        self.run_query('vehicles', '')
        self.run_query('vehicles', '')
        self.assertEqual(self.calls, 1)

    def test_retry_after_seconds_date_and_invalid(self):
        self.assertEqual(retry_seconds('120', now=0), 120)
        self.assertEqual(retry_seconds('Thu, 01 Jan 1970 00:02:00 GMT', now=0), 120)
        for value in (None, 'bad', '-1', 'NaN'):
            self.assertEqual(retry_seconds(value, now=0), 60)

    def test_processes_share_one_network_fetch(self):
        ctx = multiprocessing.get_context('spawn')
        events, start = ctx.Queue(), ctx.Event()
        workers = [ctx.Process(target=competing_reader, args=(self.path, events, start)) for _ in range(3)]
        for worker in workers:
            worker.start()
        start.set()
        for worker in workers:
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join()
            self.assertEqual(worker.exitcode, 0)
        output = [events.get(timeout=2) for _ in range(5)]
        self.assertEqual(output.count('start'), 1)
        self.assertEqual(output.count('end'), 1)
        self.assertEqual(sum(isinstance(event, tuple) for event in output), 3)

    def test_transport_429_persists_retry_after_without_retry(self):
        from unittest.mock import patch, MagicMock
        from urllib.error import HTTPError
        from zeekr_control.client import Client
        opener = MagicMock()
        opener.open.side_effect = HTTPError('https://example.invalid', 429, 'limit', {'Retry-After': '120'}, None)
        client = Client({'accessToken': 'test', 'userId': 'test'}, query_policy=self.policy)
        with patch('zeekr_control.client.build_opener', return_value=opener):
            with self.assertRaises(RateLimited):
                client.vehicles()
            with self.assertRaises(ApiError):
                Client({'accessToken': 'test', 'userId': 'test'}, query_policy=QueryPolicy(self.path, clock=lambda: self.now)).vehicles()
        self.assertEqual(opener.open.call_count, 1)

    def test_separate_client_instances_share_list_and_status(self):
        from zeekr_control.client import Client
        calls = []
        def fetch(method, url, headers, body):
            calls.append(url)
            if '/device-platform/' in url:
                return {'code': '1000', 'data': {'list': [{'vin': 'L1234567890123456'}]}}
            return {'code': '1000', 'data': {'vehicleStatus': {'chargeLevel': 48}}}
        for _ in range(2):
            client = Client({'accessToken': 'test', 'userId': 'test'}, transport=fetch,
                            query_policy=QueryPolicy(self.path, clock=lambda: self.now))
            self.assertEqual(client.vehicles()[0]['vin'], 'L1234567890123456')
            self.assertEqual(client.status('L1234567890123456'), {'chargeLevel': 48})
        self.assertEqual(len(calls), 2)
        self.assertTrue(client.last_query_cached)
        self.assertEqual(client.last_query_fetched_at, 1000)

    def test_network_deadline_survives_cache_hit_failed_attempt_and_429(self):
        self.run_query()
        self.assertEqual(getattr(self.policy, 'next_query_at', None), 1030)
        self.now += 10
        self.run_query()
        self.assertEqual(self.policy.next_query_at, 1030)
        def fail():
            raise RateLimited(120)
        self.now = 1030
        with self.assertRaises(RateLimited):
            self.policy.run('account', 'session', 'status', 'car', fail)
        self.assertEqual(self.policy.next_query_at, 1150)
        with self.assertRaises(ApiError):
            self.run_query()
        self.assertEqual(self.policy.next_query_at, 1150)

    def test_short_gateway_cooldown_does_not_extend_other_operations(self):
        def limited():
            raise RateLimited(5)
        with self.assertRaises(RateLimited):
            self.policy.run('account', 'session', 'status', 'car', limited)
        self.assertEqual(self.policy.next_query_at, 1030)
        self.now += 5
        self.assertEqual(self.run_query('vehicles', '')['data']['value'], 1)
        with self.assertRaises(ApiError):
            self.run_query()

    def set_interval(self, interval):
        save(self.path.parent / 'sampling.json', {'interval': str(interval)})

    def test_lower_interval_expires_cache_and_account_guard_together(self):
        self.run_query()
        self.set_interval(10)
        self.now += 9
        self.assertEqual(self.run_query()['data']['value'], 1)
        with self.assertRaises(ApiError) as caught:
            self.run_query(key='other')
        self.assertEqual(caught.exception.retry_after, 1)
        self.now += 1
        other = QueryPolicy(self.path, clock=lambda: self.now)
        self.assertEqual(other.run('account', 'session', 'status', 'car', self.fetch)['data']['value'], 2)
        self.assertFalse(other.cache_hit)

    def test_increase_interval_protects_other_vehicle_after_old_window(self):
        self.set_interval(10)
        self.run_query()
        self.now += 20
        self.set_interval(60)
        with self.assertRaises(ApiError) as caught:
            self.run_query(key='other')
        self.assertEqual(caught.exception.retry_after, 40)
        self.assertEqual(self.run_query()['data']['value'], 1)
        self.now += 40
        self.assertEqual(self.run_query(key='other')['data']['value'], 2)

    def test_changed_interval_never_shortens_gateway_cooldown(self):
        def limited():
            raise RateLimited(120)
        with self.assertRaises(RateLimited):
            self.policy.run('account', 'session', 'status', 'car', limited)
        self.set_interval(10)
        self.now += 10
        with self.assertRaises(ApiError) as caught:
            self.run_query()
        self.assertEqual(caught.exception.retry_after, 110)
        self.assertEqual(self.calls, 0)

    def test_failed_attempt_uses_configured_interval(self):
        self.set_interval(10)
        def fail():
            raise ApiError('failure')
        with self.assertRaises(ApiError):
            self.policy.run('account', 'session', 'status', 'car', fail)
        self.now += 9
        with self.assertRaises(ApiError):
            self.run_query()
        self.now += 1
        self.assertEqual(self.run_query()['data']['value'], 1)

    def test_other_query_caches_still_last_sixty_seconds(self):
        self.set_interval(10)
        for operation in ('vehicles', 'history', 'history_points'):
            first = self.run_query(operation, operation)
            self.now += 59
            self.assertEqual(self.run_query(operation, operation), first)
            self.now += 1
            self.assertNotEqual(self.run_query(operation, operation), first)

    def test_invalid_saved_interval_fails_without_network(self):
        for interval in ('9', '61', '30.5', 'bad'):
            self.set_interval(interval)
            with self.assertRaises(ApiError):
                self.run_query()
        self.assertEqual(self.calls, 0)

    def test_legacy_status_cooldown_is_not_discarded(self):
        from zeekr_control.query_policy import digest
        with self.policy._connect() as db:
            db.execute('CREATE TABLE cooldown (key TEXT PRIMARY KEY, until REAL NOT NULL)')
            db.execute('INSERT INTO cooldown VALUES (?, ?)', ('status:' + digest('account'), 1060))
        self.now += 30
        with self.assertRaises(ApiError) as caught:
            self.run_query()
        self.assertEqual(caught.exception.retry_after, 30)
        self.now += 30
        self.run_query()
        self.assertEqual(self.policy.next_query_at, 1090)
