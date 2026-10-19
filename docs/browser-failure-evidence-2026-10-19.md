# Z03: CI browser failure evidence

## Scope and design

This batch starts from Z02 commit `4cd0eaec282294672820fd5b022fa391539cbafe` and changes test infrastructure only. It uses explicit capture before browser teardown rather than rewriting historical CJS scripts or intercepting all Playwright activity. No application behavior or release state changes.

The collector is integrated with five synthetic desktop suites: smoke, status summary, overview dashboard, vehicle parameters, and tyre layout. A safe test ID and first repository-local assertion frame identify the failing case. Other historical suites remain outside capture coverage. Shared fixture startup captures only after a page and recorder exist. Browser crashes, cancellation, process termination, and pre-page startup failures cannot guarantee screenshots.

Default evidence root: `test-results/browser-failures`. Output is configurable, created only on failure, and never cleared. A failure owns a unique directory. PNG is limited to 8 MiB; explicitly reviewed trace is limited to 16 MiB. Diagnostic JSON stores counts and source location, without untrusted text or response bodies. Trace is disabled for application fixtures and enabled only for the reviewed static synthetic probe. Details and adoption instructions are in `docs/development.md`.

Actions uploads named allowlisted files after test failure, skips cancelled jobs, ignores an absent directory, retains artifacts for seven days, and leaves failed test status unchanged. The action is pinned to the official v4.6.2 SHA; hosted upload is deliberately not triggered in this local-only batch.

## Validation record

TDD: first new regression failed because collector module did not exist. Browser execution initially hit macOS sandbox MachPort denial; official escalation allowed the synthetic regression. First runnable regression found Chromium emitted an extra console event for the deliberately aborted network request; the assertion now requires at least one console event while exact page-error/request-failure counts remain checked. This was a test expectation correction, not suppression of a failing product assertion.

Manifest: 112 CJS files, 56 executable, 56 individually excluded. New smoke regression invokes its intentionally failing child; the child is excluded with this precise reason. Unit and static checks retain Z02 coverage.

Final command outcomes and retained private evidence are recorded in local `handoff.md` after verification. This report does not claim production, hosted CI, real-user acceptance, or coverage of unmodified legacy scripts. No mobile tests, push, merge, deployment, or next-batch execution is authorized here.

Final verification: `npm run check:desktop-manifest` passed (112 classified); `npm run test:unit` passed (20 files, including 20 isolated manifest CLI cases); `npm run check:js` passed (32 first-party static JS files). `npm run test:desktop` passed all 36 files serially in 187.2 seconds, exit 0. A focused final run of `tests/browser_failure_evidence.cjs` passed after adding PNG decoding, ZIP CRC/trace JSON parsing, screenshot/trace size limits, and capture-error checks. Changed CJS files passed Node syntax checks; `git diff --check` passed.

Environment: Node.js 26.5.0, offline `npm ci --ignore-scripts --offline`, locked Playwright 1.62.1 and Chromium 151.0.7922.34. Desktop regression used the locked executable explicitly. A separately retained synthetic assertion probe exited 1, with a 14,094-byte PNG, 488-byte JSON diagnostic, and 15,603-byte trace ZIP. The PNG was visually inspected; ZIP CRC and trace JSON parsed successfully; no response-body resource was recorded. Five migrated suites succeeded without creating the collector's default evidence directory. Synthetic capture-error tests intentionally print bounded incomplete-evidence categories; these are expected negative-path assertions.

Private evidence remains under `private/local-work-audit/z03-browser-evidence-20261019/` and is not committed. No secret files, browser profile, full terminal log, real account/position, or unchecked response body is included in tracked changes or the CI upload allowlist. Existing fixture sources and every changed path were reviewed. Remote Actions upload remains unverified until a later authorized push.
