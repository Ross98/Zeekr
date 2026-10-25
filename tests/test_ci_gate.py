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


class GitHubReadRetryTests(unittest.TestCase):
    def read(self, effects):
        from unittest.mock import patch
        with patch.object(ci.subprocess,'run',side_effect=effects) as run, patch.object(ci.time,'sleep') as sleep:
            value=ci.github_json('repos/owner/project/actions/runs')
            return value,run,sleep

    def test_transient_timeout_and_5xx_recover_with_bounded_backoff(self):
        import subprocess
        for error in (subprocess.TimeoutExpired(['gh'],15),
                      subprocess.CalledProcessError(1,['gh'],stderr='HTTP 502: Bad Gateway'),
                      subprocess.CalledProcessError(1,['gh'],stderr='TLS handshake timeout'),
                      subprocess.CalledProcessError(1,['gh'],stderr='error connecting to api.github.com')):
            value,run,sleep=self.read([error,subprocess.CompletedProcess(['gh'],0,stdout='{"workflow_runs":[]}')])
            self.assertEqual(value,{'workflow_runs':[]});self.assertEqual(run.call_count,2)
            sleep.assert_called_once_with(1)
            self.assertEqual(run.call_args.args[0],['gh','api','repos/owner/project/actions/runs'])

    def test_exhausted_transport_errors_stop_after_three_reads(self):
        import subprocess
        from unittest.mock import patch,call
        with patch.object(ci.subprocess,'run',side_effect=subprocess.TimeoutExpired(['gh'],15)) as run, patch.object(ci.time,'sleep') as sleep:
            with self.assertRaisesRegex(ValueError,'release blocked'):ci.github_json('test')
            self.assertEqual(run.call_count,3);self.assertEqual(sleep.call_args_list,[call(1),call(2)])

    def test_auth_rate_limit_missing_cli_and_invalid_json_do_not_retry(self):
        import subprocess
        from unittest.mock import patch
        for effect in [subprocess.CalledProcessError(1,['gh'],stderr='HTTP %s; EOF'%code) for code in (401,403,404,429)]+[
                FileNotFoundError('gh'),subprocess.CompletedProcess(['gh'],0,stdout='bad-json'),
                subprocess.CompletedProcess(['gh'],0,stdout='[]')]:
            with patch.object(ci.subprocess,'run',side_effect=[effect] if isinstance(effect,Exception) else None,
                              return_value=effect) as run,patch.object(ci.time,'sleep') as sleep:
                with self.assertRaises(ValueError):ci.github_json('test')
                self.assertEqual(run.call_count,1);sleep.assert_not_called()

    def test_latest_failed_run_is_not_retried_or_replaced_by_older_green(self):
        from unittest.mock import Mock
        failed=dict(id=2,run_attempt=1,head_sha='a'*40,status='completed',conclusion='failure',event='push')
        fetch=Mock(return_value={'workflow_runs':[failed,dict(failed,id=1,conclusion='success')]})
        with self.assertRaises(ValueError):ci.verify_commit('a'*40,repo='owner/project',fetch=fetch)
        self.assertEqual(fetch.call_count,1)
