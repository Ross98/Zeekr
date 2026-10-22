"""CI evidence is commit-bound and fail-closed; never contacts GitHub in tests."""
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('ci_gate',Path(__file__).parents[1]/'scripts/release/ci_gate.py')
ci=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class CIGateTests(unittest.TestCase):
    sha='a'*40

    def check(self,**changes):
        run=dict(id=123,run_attempt=2,head_sha=self.sha,status='completed',conclusion='success',event='push')
        run.update(changes)
        jobs=[dict(name=name,status='completed',conclusion='success') for name in ci.REQUIRED_JOBS]
        def fetch(endpoint):
            if '/jobs?' in endpoint:return {'jobs':jobs}
            return {'workflow_runs':[run]}
        return ci.verify_commit(self.sha,repo='owner/project',fetch=fetch)

    def test_exact_success_is_accepted(self):
        self.assertEqual(self.check()['run_id'],123)

    def test_failed_pending_cancelled_or_other_sha_never_pass(self):
        for changes in [dict(conclusion='failure'),dict(status='in_progress'),dict(conclusion='cancelled'),dict(head_sha='b'*40),dict(event='pull_request')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.check(**changes)

    def test_green_run_with_skipped_or_missing_required_job_is_rejected(self):
        run=dict(id=123,run_attempt=1,head_sha=self.sha,status='completed',conclusion='success',event='push')
        for jobs in [[],[dict(name=name,status='completed',conclusion='skipped') for name in ci.REQUIRED_JOBS]]:
            def fetch(endpoint):return {'jobs':jobs} if '/jobs?' in endpoint else {'workflow_runs':[run]}
            with self.assertRaises(ValueError):ci.verify_commit(self.sha,repo='owner/project',fetch=fetch)

    def test_newest_run_and_exact_attempt_are_required(self):
        seen=[]
        def fetch(endpoint):
            seen.append(endpoint)
            if '/jobs?' in endpoint:return {'jobs':[dict(name=name,status='completed',conclusion='success') for name in ci.REQUIRED_JOBS]}
            return {'workflow_runs':[dict(id=2,run_attempt=3,head_sha=self.sha,status='completed',conclusion='success',event='push')]}
        ci.verify_commit(self.sha,repo='owner/project',fetch=fetch)
        self.assertIn('/runs/2/attempts/3/jobs?',seen[-1])

    def test_invalid_identifiers_do_not_call_network(self):
        def fetch(endpoint):raise AssertionError('must not query')
        with self.assertRaises(ValueError):ci.verify_commit('HEAD',repo='owner/project',fetch=fetch)
        with self.assertRaises(ValueError):ci.verify_commit(self.sha,repo='../private',fetch=fetch)
