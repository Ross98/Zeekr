"""Damaged transient query caches must preserve local request protection."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock,patch

from zeekr_control.errors import RequestDeferred
from zeekr_control.query_policy import QueryPolicy


class QueryCacheRecoveryTests(unittest.TestCase):
    def test_quarantined_cache_cannot_bypass_shared_429_cooldown(self):
        with tempfile.TemporaryDirectory() as folder:
            now=[1000.0];path=Path(folder)/'queries.sqlite3';policy=QueryPolicy(path,clock=lambda:now[0])
            fetch=Mock(return_value={'valid':True});policy.run('account','session','status','car',fetch)
            with sqlite3.connect(path) as db:
                db.execute("UPDATE cache SET data='not-json'")
                db.execute("INSERT INTO cooldown VALUES('gateway',1120)")
            with self.assertRaises(RequestDeferred) as caught:policy.run('account','session','status','car',fetch)
            self.assertEqual(caught.exception.retry_after,120)
            now[0]=1060
            with self.assertRaises(RequestDeferred):policy.run('account','session','status','car',fetch)
            self.assertEqual(fetch.call_count,1)
            now[0]=1120
            policy.run('account','session','status','car',fetch)
            self.assertEqual(fetch.call_count,2)

    def test_cache_byte_boundary_and_utf8_expansion(self):
        import json
        exact={'p':'x'*(32-len(json.dumps({'p':''}).encode()))}
        self.assertEqual(len(json.dumps(exact).encode()),32)
        for payload,reusable in ((exact,True),({'p':'测'*10},False)):
            with self.subTest(reusable=reusable),tempfile.TemporaryDirectory() as folder:
                policy=QueryPolicy(Path(folder)/'queries.sqlite3',clock=lambda:1000.0);fetch=Mock(return_value=payload)
                with patch('zeekr_control.query_policy.MAX_CACHE_BYTES',32):
                    self.assertEqual(policy.run('account','session','status','car',fetch),payload)
                    if reusable:
                        self.assertEqual(policy.run('account','session','status','car',fetch),payload)
                        self.assertTrue(policy.cache_hit)
                    else:
                        with self.assertRaises(RequestDeferred):policy.run('account','session','status','car',fetch)
                fetch.assert_called_once()

    def test_bad_cache_is_not_reported_as_a_successful_client_read(self):
        from zeekr_control.client import Client
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'queries.sqlite3';policy=QueryPolicy(path,clock=lambda:1000.0)
            wire=Mock(return_value={'code':'1000','data':{'vehicleStatus':{'updateTime':1000000,'value':1}}})
            client=Client({'accessToken':'synthetic-access','userId':'synthetic-user'},transport=wire,query_policy=policy)
            vin='L6T79X2Z0NP000001'
            client.status(vin)
            with sqlite3.connect(path) as db:db.execute('UPDATE cache SET data=?',('{"vehicleStatus":{"value":NaN}}',))
            with self.assertRaises(RequestDeferred):client.status(vin)
            self.assertFalse(client.last_query_cached)
            self.assertFalse(client.query_outcome.actual_request)
            self.assertFalse(client.query_outcome.schema_valid)
            wire.assert_called_once()

    def test_bad_cache_is_quarantined_until_original_interval_then_repaired(self):
        for operation,interval in (('status',30),('vehicles',60)):
            for encoded in ('not-json','['*10000+'0'+']'*10000,'{"value":NaN}','{"value":1e999}'):
                with self.subTest(operation=operation,encoded=encoded[:24]),tempfile.TemporaryDirectory() as folder:
                    now=[1000.0];path=Path(folder)/'queries.sqlite3';policy=QueryPolicy(path,clock=lambda:now[0])
                    fetch=Mock(return_value={'valid':True})
                    policy.run('account','session',operation,'car',fetch)
                    with sqlite3.connect(path) as db:db.execute('UPDATE cache SET data=?',(encoded,))
                    with self.assertRaises(RequestDeferred):policy.run('account','session',operation,'car',fetch)
                    self.assertFalse(policy.cache_hit)
                    self.assertIsNone(policy.fetched_at)
                    self.assertEqual(fetch.call_count,1)
                    with sqlite3.connect(path) as db:self.assertEqual(db.execute('SELECT data FROM cache').fetchone()[0],'')
                    with self.assertRaises(RequestDeferred):policy.run('account','session',operation,'car',fetch)
                    self.assertEqual(fetch.call_count,1)
                    now[0]+=interval;fetch.return_value={'valid':'repaired'}
                    self.assertEqual(policy.run('account','session',operation,'car',fetch),fetch.return_value)
                    self.assertEqual(fetch.call_count,2)

    def test_oversized_cache_never_reaches_json_parser(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'queries.sqlite3';policy=QueryPolicy(path,clock=lambda:1000.0)
            fetch=Mock(return_value={'valid':True})
            policy.run('account','session','status','car',fetch)
            with sqlite3.connect(path) as db:db.execute('UPDATE cache SET data=?',('{"pad":"'+'x'*100+'"}',))
            with patch('zeekr_control.query_policy.MAX_CACHE_BYTES',32,create=True),\
                 patch('zeekr_control.query_policy.json.loads',side_effect=AssertionError('oversized cache parsed')):
                with self.assertRaises(RequestDeferred):policy.run('account','session','status','car',fetch)
            self.assertEqual(fetch.call_count,1)

    def test_large_fresh_response_still_returns_but_keeps_only_cache_metadata(self):
        for operation in ('status','vehicles'):
            with self.subTest(operation=operation),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'queries.sqlite3';policy=QueryPolicy(path,clock=lambda:1000.0)
                fetch=Mock(return_value={'pad':'x'*100})
                with patch('zeekr_control.query_policy.MAX_CACHE_BYTES',32,create=True):
                    self.assertEqual(policy.run('account','session',operation,'car',fetch),fetch.return_value)
                    with sqlite3.connect(path) as db:self.assertEqual(db.execute('SELECT data FROM cache').fetchone()[0],'')
                    with self.assertRaises(RequestDeferred):policy.run('account','session',operation,'car',fetch)
                self.assertEqual(fetch.call_count,1)
