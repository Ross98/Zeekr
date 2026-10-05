"""Stable timed entrypoint. stage / deploy (automatic rollback) / verify / rollback."""
import argparse
import fcntl
import json
from pathlib import Path
import runpy
import subprocess
import time

base = Path('/opt/zeekr-control')


def phase(name):
    started = time.monotonic()
    passed = False
    original_run = subprocess.run
    def timed_run(argv, *args, **kwargs):
        command_start = time.monotonic()
        try:
            return original_run(argv, *args, **kwargs)
        finally:
            record = dict(phase=name, program=Path(argv[0]).name, seconds=round(time.monotonic()-command_start, 3))
            with (base/'.release-timings.jsonl').open('a') as output:
                output.write(json.dumps(record)+'\n')
            print('RELEASE_COMMAND_TIMING '+json.dumps(record), flush=True)
    subprocess.run = timed_run
    try:
        runpy.run_path(str(base/('.release-'+name+'.py')), run_name='__main__')
        passed = True
    finally:
        subprocess.run = original_run
        result = dict(phase=name, seconds=round(time.monotonic()-started, 3), passed=passed)
        with (base/'.release-timings.jsonl').open('a') as output:
            output.write(json.dumps(result)+'\n')
        print('RELEASE_TIMING '+json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stage', 'deploy', 'verify', 'rollback'])
    args = parser.parse_args()
    with (base/'.release-operation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action != 'deploy':
            phase(args.action)
            return
        # cutover rolls back internally if starting services fails.
        phase('cutover')
        try:
            phase('verify')
        except BaseException:
            phase('rollback')
            raise


if __name__ == '__main__':
    main()
