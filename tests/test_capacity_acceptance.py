"""Memory evidence must retain peaks and reclaim events after a cgroup exits."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('capacity_acceptance',
    Path(__file__).resolve().parents[1] / 'scripts' / 'capacity_acceptance.py')
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class CapacityAcceptanceTests(unittest.TestCase):
    def test_disappeared_unit_cannot_pass_or_crash_evidence_collection(self):
        row = dict(state=dict(Result='success', ExecMainStatus='0', MemoryMax='infinity'),
                   memory=dict(oom=0, oom_kill=0, peak_bytes=2048), workload=None)
        self.assertFalse(acceptance.workload_passed(row))

    def test_completed_workload_requires_a_finite_limit_and_no_oom(self):
        row = dict(state=dict(Result='success', ExecMainStatus='0', MemoryMax='4096'),
                   memory=dict(oom=0, oom_kill=0, peak_bytes=2048), workload=dict(records=31))
        self.assertTrue(acceptance.workload_passed(row))
        row['memory']['oom'] = 1
        self.assertFalse(acceptance.workload_passed(row))

    def test_memory_sampling_retains_peak_components_and_high_events(self):
        with tempfile.TemporaryDirectory() as folder:
            group = Path(folder)
            (group / 'memory.events').write_text('high 7\nmax 3\noom 0\noom_kill 0\n')
            (group / 'memory.current').write_text('9000\n')
            (group / 'memory.stat').write_text('anon 6000\nfile 2000\ninactive_file 1500\nfile_dirty 100\n')
            sample = dict(oom=0, oom_kill=0, peak_bytes=0)
            acceptance.sample_memory(group, sample)
            (group / 'memory.current').write_text('3000\n')
            (group / 'memory.stat').write_text('anon 1000\nfile 1000\n')
            acceptance.sample_memory(group, sample)
            self.assertEqual(sample['current_peak_bytes'], 9000)
            self.assertEqual(sample['anon_peak_bytes'], 6000)
            self.assertEqual(sample['file_peak_bytes'], 2000)
            self.assertEqual(sample['high'], 7)
            self.assertEqual(sample['max'], 3)
            self.assertEqual(sample['stat_at_sampled_peak']['inactive_file'], 1500)
            self.assertEqual(sample['stat_at_sampled_peak']['file_dirty'], 100)
            for path in group.iterdir():
                path.unlink()
            acceptance.sample_memory(group, sample)
            self.assertEqual(sample['high'], 7)
