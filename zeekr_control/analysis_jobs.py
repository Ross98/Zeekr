"""Bounded read workers with independent, short-lived result subscriptions."""
import json
import secrets
import threading
import time

from .analysis_cancel import AnalysisCancelled, cancellation_scope, check_cancelled


class JobsBusy(ValueError):
    pass


class AnalysisJobs:
    def __init__(self, clock=time.monotonic, max_bytes=8*1024*1024):
        self.clock, self.max_bytes = clock, max_bytes
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(2)
        self.jobs = {}
        self.pending = {}

    def _encode(self, data):
        body = bytearray()
        for fragment in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(data):
            check_cancelled()
            chunk = fragment.encode()
            if len(body)+len(chunk) > self.max_bytes:
                raise OverflowError('analysis result limit')
            body.extend(chunk)
        return bytes(body)

    def _detach(self, ticket):
        subscription = self.jobs.pop(ticket)
        task = subscription['task']
        task['tickets'].discard(ticket)
        if not task['tickets']:
            task['cancel'].set()
            if self.pending.get(task['key']) is task:
                del self.pending[task['key']]

    def _clean(self):
        now = self.clock()
        for ticket, subscription in list(self.jobs.items()):
            task = subscription['task']
            if ((task['done'] is not None and now-task['done'] > 120)
                    or (task['done'] is None and now-subscription['seen'] > 30)):
                self._detach(ticket)

    def submit(self, identity, read, key=None, alive=None):
        ticket = secrets.token_hex(16)
        task_key = (identity, key) if key is not None else (identity, ticket)
        with self.lock:
            self._clean()
            if len(self.jobs) >= 4:
                raise JobsBusy('还有分析结果等待读取，请稍后重试。')
            task = self.pending.get(task_key)
            if task is None:
                if not self.slots.acquire(blocking=False):
                    raise JobsBusy('历史分析正在处理其他查询，请稍后重试。')
                task = dict(key=task_key, tickets=set(), cancel=threading.Event(), done=None, response=None)
                self.pending[task_key] = task
                start = True
            else:
                start = False
            task['tickets'].add(ticket)
            self.jobs[ticket] = dict(identity=identity, task=task, seen=self.clock())
        if not start:
            return ticket

        next_clean = [self.clock()]
        def cancelled():
            if task['cancel'].is_set():
                return True
            now = self.clock()
            if now >= next_clean[0]:
                with self.lock:
                    self._clean()
                next_clean[0] = now+.25
                if alive is not None:
                    try:
                        valid = alive()
                    except Exception:
                        valid = False
                    if not valid:
                        with self.lock:
                            for subscriber in list(task['tickets']):
                                self._detach(subscriber)
            return task['cancel'].is_set()

        def run():
            response = None
            try:
                with cancellation_scope(cancelled):
                    status, data = read()
                    check_cancelled()
                    response = status, self._encode(data)
            except AnalysisCancelled:
                pass
            except OverflowError:
                response = 503, json.dumps({'error':'分析结果过大，请缩小日期范围。','code':'analysis_capacity'}).encode()
            except Exception:
                response = 503, json.dumps({'error':'本地分析暂不可用，请稍后重试。','code':'analysis_unavailable'}).encode()
            finally:
                with self.lock:
                    task.update(done=self.clock(), response=response)
                    if self.pending.get(task_key) is task:
                        del self.pending[task_key]
                    self._clean()
                self.slots.release()
        try:
            threading.Thread(target=run, daemon=True, name='zeekr-read-analysis').start()
        except Exception:
            with self.lock:
                for subscriber in list(task['tickets']):
                    self._detach(subscriber)
            self.slots.release()
            raise
        return ticket

    def finished(self, ticket):
        with self.lock:
            subscription = self.jobs.get(ticket)
            return bool(subscription and subscription['task']['done'] is not None)

    def cancel(self, ticket, identity):
        with self.lock:
            self._clean()
            subscription = self.jobs.get(ticket)
            if not subscription or subscription['identity'] != identity:
                return 404, {'error':'分析结果已失效，请重新读取。','code':'analysis_expired'}
            self._detach(ticket)
            return 200, {'cancelled':True}

    def poll(self, ticket, identity):
        with self.lock:
            self._clean()
            subscription = self.jobs.get(ticket)
            if not subscription or subscription['identity'] != identity:
                return 404, {'error':'分析结果已失效，请重新读取。','code':'analysis_expired'}
            subscription['seen'] = self.clock()
            task = subscription['task']
            if task['done'] is None:
                return 202, {'analysis_job_url':'/api/analysis/'+ticket,'retry_after_ms':750}
            response = task['response']
            self._detach(ticket)
            return response or (409, {'error':'分析已取消。','code':'analysis_cancelled'})
