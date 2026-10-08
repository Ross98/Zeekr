import json
import threading
import time
import unittest
from unittest.mock import patch

import test_readonly_analysis as context_tests
from zeekr_control.analysis_jobs import AnalysisJobs, JobsBusy


class AnalysisJobsTests(unittest.TestCase):
    def test_slow_job_returns_ticket_and_does_not_block_poll(self):
        jobs=AnalysisJobs();release=threading.Event();entered=threading.Event()
        def read():
            entered.set();release.wait(3);return 200,{'value':1}
        ticket=jobs.submit('account',read);self.assertTrue(entered.wait(1))
        self.assertEqual(jobs.poll(ticket,'account')[0],202)
        self.assertEqual(jobs.poll(ticket,'other')[0],404)
        release.set()
        for _ in range(100):
            status,body=jobs.poll(ticket,'account')
            if status!=202:break
            time.sleep(.01)
        self.assertEqual((status,json.loads(body)),(200,{'value':1}))
        self.assertEqual(jobs.poll(ticket,'account')[0],404)

    def test_capacity_is_bounded_and_expired_results_are_discarded(self):
        now=[1];jobs=AnalysisJobs(clock=lambda:now[0]);release=threading.Event()
        tickets=[jobs.submit('a',lambda:(release.wait(2) and 200,{})) for _ in range(2)]
        with self.assertRaises(JobsBusy):jobs.submit('a',lambda:(200,{}))
        release.set()
        for _ in range(100):
            if all(jobs.finished(ticket) for ticket in tickets):break
            time.sleep(.01)
        now[0]+=121
        self.assertEqual(jobs.poll(tickets[0],'a')[0],404)

    def test_oversized_result_is_not_retained(self):
        jobs=AnalysisJobs(max_bytes=32)
        ticket=jobs.submit('a',lambda:(200,{'data':'x'*100}))
        for _ in range(100):
            if jobs.finished(ticket):break
            time.sleep(.01)
        self.assertEqual(jobs.poll(ticket,'a')[0],503)

    def test_unclaimed_results_survive_later_jobs_until_capacity(self):
        jobs=AnalysisJobs();tickets=[]
        for _ in range(4):
            ticket=jobs.submit('a',lambda:(200,{'ok':True}));tickets.append(ticket)
            for _ in range(100):
                if jobs.finished(ticket):break
                time.sleep(.01)
        with self.assertRaises(JobsBusy):jobs.submit('a',lambda:(200,{}))
        for ticket in tickets:self.assertEqual(jobs.poll(ticket,'a')[0],200)


class AnalysisJobsContextTests(unittest.TestCase):
    setUp = context_tests.ReadonlyAnalysisTests.setUp
    def test_completed_job_cannot_be_read_after_account_switch(self):
        from zeekr_control.storage import save
        ticket=self.app.start_analysis(lambda:{'context':'private-old','value':1})
        for _ in range(100):
            if self.app.analysis_jobs.finished(ticket):break
            time.sleep(.01)
        save(self.path,{'userId':'other','accessToken':'OTHER'})
        status,body=self.app.poll_analysis(ticket)
        self.assertEqual(status,404)
        self.assertNotIn('private-old',str(body))

    def test_http_ticket_allows_state_and_returns_real_result(self):
        import http.client
        from zeekr_control.web import make_server
        server=make_server(self.app,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join()))
        def get(path,prefer=False):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
            conn.request('GET',path,headers={'Prefer':'respond-async'} if prefer else {})
            response=conn.getresponse();body=json.loads(response.read());conn.close()
            return response.status,body
        entered,release=threading.Event(),threading.Event()
        def read(*args,**kwargs):
            entered.set();release.wait(3);return {'calendar_complete':True}
        with patch.object(self.app.usage_calendar,'query',side_effect=read):
            status,ticket=get('/api/insights/calendar?date=2026-10-08',True)
            self.assertEqual(status,202);self.assertTrue(entered.wait(1))
            self.assertEqual(get('/api/state')[0],200)
            self.assertEqual(get(ticket['analysis_job_url'])[0],202)
            release.set()
            for _ in range(100):
                status,body=get(ticket['analysis_job_url'])
                if status!=202:break
                time.sleep(.01)
            self.assertEqual(status,200);self.assertTrue(body['calendar_complete'])
