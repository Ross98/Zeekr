"""Small, ephemeral read-result mailbox; no durable jobs or unbounded queue."""
import json
import secrets
import threading
import time


class JobsBusy(ValueError):
    pass


class AnalysisJobs:
    def __init__(self, clock=time.monotonic, max_bytes=8*1024*1024):
        self.clock, self.max_bytes = clock, max_bytes
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(2)
        self.jobs = {}

    def _encode(self, data):
        body = bytearray()
        for fragment in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(data):
            chunk = fragment.encode()
            if len(body)+len(chunk) > self.max_bytes:
                raise OverflowError('analysis result limit')
            body.extend(chunk)
        return bytes(body)

    def _clean(self):
        now = self.clock()
        for ticket, job in list(self.jobs.items()):
            if job['done'] is not None and now-job['done'] > 120:
                del self.jobs[ticket]

    def submit(self, identity, read):
        if not self.slots.acquire(blocking=False):
            raise JobsBusy('历史分析正在处理其他查询，请稍后重试。')
        ticket = secrets.token_hex(16)
        with self.lock:
            self._clean()
            # Never evict a still-valid ticket to accept new work.
            if len(self.jobs) >= 4:
                self.slots.release()
                raise JobsBusy('还有分析结果等待读取，请稍后重试。')
            self.jobs[ticket] = dict(identity=identity, done=None, response=None)
        def run():
            try:
                status, data = read()
                body = self._encode(data)
            except OverflowError:
                status, body = 503, json.dumps({'error':'分析结果过大，请缩小日期范围。','code':'analysis_capacity'}).encode()
            except Exception:
                status, body = 503, json.dumps({'error':'本地分析暂不可用，请稍后重试。','code':'analysis_unavailable'}).encode()
            finally:
                with self.lock:
                    self.jobs[ticket].update(done=self.clock(), response=(status, body))
                    self._clean()
                self.slots.release()
        try:
            threading.Thread(target=run, daemon=True, name='zeekr-read-analysis').start()
        except Exception:
            with self.lock: self.jobs.pop(ticket, None)
            self.slots.release()
            raise
        return ticket

    def finished(self, ticket):
        with self.lock:
            job = self.jobs.get(ticket)
            return bool(job and job['done'] is not None)

    def poll(self, ticket, identity):
        with self.lock:
            self._clean()
            job = self.jobs.get(ticket)
            if not job or job['identity'] != identity:
                return 404, {'error':'分析结果已失效，请重新读取。','code':'analysis_expired'}
            if job['done'] is None:
                return 202, {'analysis_job_url':'/api/analysis/'+ticket,'retry_after_ms':750}
            del self.jobs[ticket]
            return job['response']
