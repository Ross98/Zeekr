"""Read-only, exact-commit GitHub Actions gate. No local receipt can replace it."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

REQUIRED_JOBS=('Python tests','Desktop tests','macOS native tests','Workflow checks')


def _transient(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return True
    if not isinstance(error, subprocess.CalledProcessError):
        return False
    detail = error.stderr or ''
    if isinstance(detail, bytes):
        detail = detail.decode('utf-8', errors='replace')
    status = re.search(r'\bHTTP(?:/\S+)?\s+(\d{3})\b', detail, re.I)
    if status:
        return 500 <= int(status.group(1)) < 600
    return any(reason in detail.lower() for reason in (
        'tls handshake timeout', 'connection reset', 'connection refused',
        'unexpected eof', ': eof', 'i/o timeout', 'network is unreachable',
        'could not resolve host', 'temporary failure in name resolution',
        'no such host', 'failed to connect', 'error connecting to', 'context deadline exceeded'))


def github_json(endpoint):
    # Read-only transport retries only. Never retry a returned CI failure or
    # auth/rate-limit rejection, and never select an older successful run.
    for attempt in range(3):
        try:
            result = subprocess.run(['gh', 'api', endpoint], capture_output=True,
                                    text=True, check=True, timeout=15)
            value = json.loads(result.stdout)
            if not isinstance(value, dict):
                raise ValueError('Invalid GitHub response')
            return value
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            if attempt < 2 and _transient(error):
                time.sleep(attempt + 1)
                continue
            raise ValueError('GitHub CI evidence unavailable; release blocked') from None


def repository():
    try:
        root=Path(__file__).resolve().parents[2]
        remote=subprocess.check_output(['git','config','--get','remote.origin.url'],cwd=root,text=True,timeout=5).strip()
        match=re.fullmatch(r'(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?',remote)
        if not match:raise ValueError()
        return match[1]
    except (OSError,subprocess.SubprocessError,ValueError):
        raise ValueError('Expected a configured GitHub origin for CI verification') from None


def verify_commit(commit,repo=None,fetch=github_json):
    if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('CI requires a full commit SHA')
    repo=repository() if repo is None else repo
    if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('Invalid GitHub repository')
    runs=fetch('repos/'+repo+'/actions/workflows/tests.yml/runs?head_sha='+commit+'&event=push&per_page=100').get('workflow_runs',[])
    # GitHub returns newest first. Never fall back to an older green run after
    # the exact commit's newest run failed, was cancelled or remains pending.
    if not runs:raise ValueError('No push CI run for candidate commit; push and wait before release')
    run=runs[0]
    if (run.get('head_sha')!=commit or run.get('event')!='push' or
            run.get('status')!='completed' or run.get('conclusion')!='success'):
        raise ValueError('Candidate commit CI is not successful; release blocked')
    run_id=run.get('id');attempt=run.get('run_attempt')
    if type(run_id) is not int or type(attempt) is not int or run_id<=0 or attempt<=0:raise ValueError('Invalid CI run identity')
    jobs=fetch('repos/'+repo+'/actions/runs/'+str(run_id)+'/attempts/'+str(attempt)+'/jobs?per_page=100').get('jobs',[])
    for name in REQUIRED_JOBS:
        matching=[job for job in jobs if job.get('name')==name]
        if len(matching)!=1 or matching[0].get('status')!='completed' or matching[0].get('conclusion')!='success':
            raise ValueError('Required CI job missing or unsuccessful: '+name)
    return dict(commit=commit,repository=repo,run_id=run_id,attempt=attempt,jobs=list(REQUIRED_JOBS))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit',required=True);parser.add_argument('--repo')
    args=parser.parse_args()
    print(json.dumps(verify_commit(args.commit,args.repo)))
