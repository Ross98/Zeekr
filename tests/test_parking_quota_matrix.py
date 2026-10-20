"""Acceptance must distinguish missing results, quota pressure and cancellation."""
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('parking_quota_matrix',Path(__file__).resolve().parents[1]/'scripts/parking_quota_matrix.py')
matrix=importlib.util.module_from_spec(spec);spec.loader.exec_module(matrix)


class ParkingQuotaMatrixTests(unittest.TestCase):
    def good(self):
        return dict(status='ok',elapsed_seconds=59,memory_peak_bytes=180*1024*1024,
                    memory_events=dict(oom=0,oom_kill=0,max=0),response_sha256='same',
                    cache_state='same_process_after_complete_query')

    def test_missing_response_or_memory_limit_pressure_never_passes(self):
        row=self.good();plan=dict(range='day')
        self.assertTrue(matrix.assess(row,plan,'cold','same')['passed'])
        for change in [dict(status='worker_killed'),dict(memory_peak_bytes=193*1024*1024),
                       dict(memory_peak_bytes=0),dict(elapsed_seconds=61),dict(response_sha256='different'),
                       dict(memory_events=dict(oom=0,oom_kill=0,max=1)),dict(memory_events={})]:
            with self.subTest(change=change):self.assertFalse(matrix.assess(dict(row,**change),plan,'cold','same')['passed'])

    def test_partially_warm_failed_work_is_not_a_valid_warm_sample(self):
        row=self.good();row['cache_state']='partial_after_failed_query'
        self.assertFalse(matrix.assess(row,dict(range='month'),'warm','same')['passed'])
        self.assertFalse(matrix.assess(self.good(),dict(range='month'),'cold',None)['passed'])

    def test_cancel_ack_alone_does_not_prove_cleanup(self):
        row=dict(self.good(),cancelled=True,cleanup_seconds=.1,slots_released=True,scratch_remaining=[])
        self.assertTrue(matrix.assess(row,dict(range='day'),'cancel',None)['passed'])
        for change in [dict(slots_released=False),dict(cleanup_seconds=2.1),dict(scratch_remaining=['leaked.sqlite3']),dict(cancelled=False)]:
            with self.subTest(change=change):self.assertFalse(matrix.assess(dict(row,**change),dict(range='day'),'cancel',None)['passed'])


if __name__=='__main__':unittest.main()
