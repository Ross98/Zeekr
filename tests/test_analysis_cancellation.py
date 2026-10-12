import json
import threading
import unittest

from zeekr_control.analysis_jobs import AnalysisJobs, JobsBusy


class SharedAnalysisTests(unittest.TestCase):
    def wait_done(self, jobs, ticket):
        import time
        deadline=time.monotonic()+2
        while not jobs.finished(ticket) and time.monotonic()<deadline:
            time.sleep(.005)
        self.assertTrue(jobs.finished(ticket))

    def test_same_key_computes_once_and_each_waiter_receives_result(self):
        jobs=AnalysisJobs();release=threading.Event();entered=threading.Event();calls=[]
        self.addCleanup(release.set)
        def read():
            calls.append(1);entered.set();release.wait(2);return 200,{'value':42}
        first=jobs.submit('a',read,key=('month','v1'))
        self.assertTrue(entered.wait(1))
        second=jobs.submit('a',read,key=('month','v1'))
        self.assertNotEqual(first,second)
        third=jobs.submit('a',lambda:(release.wait(2) and 200,{'other':1}),key=('week','v1'))
        with self.assertRaises(JobsBusy):jobs.submit('a',read,key=('day','v1'))
        release.set();self.wait_done(jobs,first);self.wait_done(jobs,third)
        self.assertEqual(calls,[1])
        for ticket in (first,second):
            status,body=jobs.poll(ticket,'a');self.assertEqual((status,json.loads(body)),(200,{'value':42}))

    def test_cancel_one_waiter_preserves_shared_work_and_identity(self):
        jobs=AnalysisJobs();release=threading.Event();self.addCleanup(release.set)
        first=jobs.submit('a',lambda:(release.wait(2) and 200,{'ok':1}),key='month')
        second=jobs.submit('a',lambda:(500,{}),key='month')
        self.assertEqual(jobs.cancel(first,'other')[0],404)
        self.assertEqual(jobs.cancel(first,'a')[0],200)
        self.assertEqual(jobs.poll(first,'a')[0],404)
        self.assertEqual(jobs.poll(second,'a')[0],202)
        release.set();self.wait_done(jobs,second)
        self.assertEqual(json.loads(jobs.poll(second,'a')[1]),{'ok':1})

    def test_last_cancel_exits_and_releases_slot_after_cleanup(self):
        from zeekr_control.analysis_cancel import check_cancelled
        jobs=AnalysisJobs();entered=threading.Event();exited=threading.Event()
        def read():
            entered.set()
            try:
                while True:check_cancelled()
            finally:exited.set()
        first=jobs.submit('a',read,key='month');self.assertTrue(entered.wait(1))
        jobs.cancel(first,'a');self.assertTrue(exited.wait(1))
        # Both slots are eventually reusable, including the cancelled worker's slot.
        import time
        deadline=time.monotonic()+1
        while not jobs.slots.acquire(blocking=False) and time.monotonic()<deadline:time.sleep(.005)
        self.assertTrue(jobs.slots.acquire(blocking=False));jobs.slots.release();jobs.slots.release()

    def test_revision_and_account_are_not_merged(self):
        for identity,key in [('a','v2'),('b','v1')]:
            jobs=AnalysisJobs();release=threading.Event();calls=[];self.addCleanup(release.set)
            def read():calls.append(1);release.wait(2);return 200,{}
            first=jobs.submit('a',read,key='v1');second=jobs.submit(identity,read,key=key)
            release.set();self.wait_done(jobs,first);self.wait_done(jobs,second)
            self.assertEqual(len(calls),2)

    def test_sqlite_query_is_interrupted_and_temporary_file_removed(self):
        from pathlib import Path
        from zeekr_control.analysis_work import WorkDatabase
        jobs=AnalysisJobs();entered=threading.Event();exited=threading.Event();paths=[]
        def read():
            try:
                with WorkDatabase() as work:
                    paths.append(work.path);entered.set()
                    work.db.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
                return 200,{}
            finally:exited.set()
        ticket=jobs.submit('a',read,key='long-sql');self.assertTrue(entered.wait(1))
        jobs.cancel(ticket,'a');self.assertTrue(exited.wait(1))
        self.assertFalse(Path(paths[0]).exists())
        self.assertEqual(jobs.poll(ticket,'a')[0],404)

    def test_no_slot_release_before_cancelled_worker_finishes_cleanup(self):
        from zeekr_control.analysis_cancel import check_cancelled
        jobs=AnalysisJobs();entered=threading.Event();cleaning=threading.Event();release=threading.Event()
        self.addCleanup(release.set)
        def read():
            entered.set()
            try:
                while True:check_cancelled()
            finally:cleaning.set();release.wait(2)
        first=jobs.submit('a',read,key='first');self.assertTrue(entered.wait(1))
        jobs.submit('a',lambda:(release.wait(2) and 200,{}),key='second')
        jobs.cancel(first,'a');self.assertTrue(cleaning.wait(1))
        with self.assertRaises(JobsBusy):jobs.submit('a',lambda:(200,{}),key='third')

    def test_abandoned_waiter_stops_without_cancel_delivery(self):
        from zeekr_control.analysis_cancel import check_cancelled
        now=[0];jobs=AnalysisJobs(clock=lambda:now[0]);entered=threading.Event();exited=threading.Event()
        def read():
            entered.set()
            try:
                while True:check_cancelled()
            finally:exited.set()
        ticket=jobs.submit('a',read,key='abandoned');self.assertTrue(entered.wait(1))
        now[0]=31;self.assertTrue(exited.wait(1));self.assertEqual(jobs.poll(ticket,'a')[0],404)


class AnalysisHttpCancellationTests(unittest.TestCase):
    from test_readonly_analysis import ReadonlyAnalysisTests
    setUp=ReadonlyAnalysisTests.setUp

    def test_http_shares_query_and_cancels_last_waiter_with_origin_guard(self):
        import http.client
        import time
        from unittest.mock import patch
        from zeekr_control.web import make_server
        from zeekr_control.analysis_cancel import check_cancelled
        server=make_server(self.app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join()))
        origin='http://127.0.0.1:'+str(server.server_port)
        def request(path,method='GET',key=True):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
            headers={'Prefer':'respond-async'}
            if method=='POST':headers.update({'Content-Type':'application/json','Origin':origin,'X-Request-Key':self.app.request_key if key else 'wrong'})
            conn.request(method,path,body='{}' if method=='POST' else None,headers=headers)
            response=conn.getresponse();value=json.loads(response.read());conn.close();return response.status,value
        entered=threading.Event();exited=threading.Event();calls=[]
        def read(*args,**kwargs):
            calls.append(1);entered.set()
            try:
                while True:
                    check_cancelled();time.sleep(.005)
            finally:exited.set()
        with patch.object(self.app.usage_calendar,'query',side_effect=read):
            status,first=request('/api/insights/calendar?date=2026-10-08');self.assertEqual(status,202);self.assertTrue(entered.wait(1))
            status,second=request('/api/insights/calendar?date=2026-10-08');self.assertEqual(status,202)
            self.assertEqual(len(calls),1)
            one,two=first['analysis_job_url'],second['analysis_job_url']
            self.assertEqual(request(one+'/cancel','POST',False)[0],403)
            self.assertEqual(request(one+'/cancel','POST')[0],200)
            self.assertFalse(exited.is_set());self.assertEqual(request(two)[0],202)
            self.assertEqual(request(two+'/cancel','POST')[0],200);self.assertTrue(exited.wait(1))
            self.assertEqual(request(two)[0],404)

    def test_account_switch_stops_running_worker_without_poll(self):
        from zeekr_control.storage import save
        from zeekr_control.analysis_cancel import check_cancelled
        entered=threading.Event();exited=threading.Event();release=threading.Event()
        self.addCleanup(release.set)
        def read():
            entered.set()
            try:
                while not release.wait(.005):check_cancelled()
                return {}
            finally:exited.set()
        self.app.start_analysis(read,key='account-switch')
        self.assertTrue(entered.wait(1))
        save(self.path,{'userId':'other','accessToken':'OTHER'})
        self.assertTrue(exited.wait(1),'account switch must stop old computation without polling')


class EventReadCancellationTests(unittest.TestCase):
    def test_cancelled_event_read_does_not_open_database(self):
        import tempfile
        from pathlib import Path
        from zeekr_control.usage_events import UsageEvents
        from zeekr_control.analysis_cancel import cancellation_scope, AnalysisCancelled
        stop=[False]
        with tempfile.TemporaryDirectory() as root:
            events=UsageEvents(Path(root)/'absent.sqlite3')
            with cancellation_scope(lambda:stop[0]):
                stop[0]=True
                with self.assertRaises(AnalysisCancelled):
                    with events.connect():pass
