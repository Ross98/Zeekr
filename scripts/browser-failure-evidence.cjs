// Explicit opt-in only: callers own the synthetic fixture and catch before teardown.
const fs = require('node:fs');
const path = require('node:path');
const {randomUUID} = require('node:crypto');
const runId = `${Date.now()}-${randomUUID()}`;
const limits = {'page.png': 8 * 1024 * 1024, 'trace.zip': 16 * 1024 * 1024};

async function startEvidence(page, {testId, synthetic = false, trace = false, reviewedTrace = false,
  outputDir = process.env.BROWSER_ARTIFACT_DIR || path.resolve(__dirname, '../test-results/browser-failures')} = {}) {
  if (!synthetic) throw Error('Failure evidence requires an explicitly synthetic fixture');
  if (trace && !reviewedTrace) throw Error('Trace requires reviewedTrace: response bodies must be reviewed synthetic data');
  if (!testId || typeof testId !== 'string') throw Error('Failure evidence requires a testId');
  const safeId = testId.replace(/[^a-zA-Z0-9_-]/g, '-').slice(0, 100);
  const events = {console: 0, pageerror: 0, requestfailed: 0};
  // Store counts only. Never collect text, URLs, headers, cookies, bodies or assertion values.
  const listeners = Object.keys(events).map(event => {
    const listener = () => { events[event]++; };
    page.on(event, listener);
    return [event, listener];
  });
  const captureErrors = [];
  function location(error) {
    for (const line of String(error?.stack || '').split('\n')) {
      if (!/^\s*at /.test(line)) continue;
      const match = line.match(/\(?([^()\s]+\.cjs):(\d+):(\d+)\)?$/);
      if (!match) continue;
      const file = path.relative(path.resolve(__dirname, '..'), match[1]);
      if (/^tests\/[a-zA-Z0-9_./-]+\.cjs$/.test(file) && !file.includes('..'))
        return {file, line: Number(match[2]), column: Number(match[3])};
    }
    return null;
  }
  let tracing = false, failed = false;
  if (trace) {
    try { await page.context().tracing.start({screenshots: true, snapshots: true, sources: false}); tracing = true; }
    catch { captureErrors.push('trace-start'); }
  }
  async function attempt(label, action) {
    try { await action(); } catch { captureErrors.push(label); }
  }
  return {
    async fail(error) {
      if (failed) return;
      failed = true;
      // No deletion of caller directories. Every capture owns a newly created directory.
      await attempt('output-directory', async () => {
        fs.mkdirSync(outputDir, {recursive: true, mode: 0o700});
        const directory = fs.mkdtempSync(path.join(outputDir, `${safeId}-${runId}-`));
        await attempt('screenshot', () => page.screenshot({path: path.join(directory, 'page.png'), timeout: 5000, fullPage: false}));
        if (tracing) {
          await attempt('trace-stop', () => page.context().tracing.stop({path: path.join(directory, 'trace.zip')}));
          tracing = false;
        }
        for (const [name, limit] of Object.entries(limits)) {
          const file = path.join(directory, name);
          if (fs.existsSync(file) && fs.statSync(file).size > limit) {
            fs.unlinkSync(file); captureErrors.push(`${name}-size-limit`);
          }
        }
        fs.writeFileSync(path.join(directory, 'diagnostic.json'), JSON.stringify({
          schema: 1, testId: safeId, runId, timestamp: new Date().toISOString(),
          error: {name: error?.name === 'AssertionError' ? 'AssertionError' : 'Error', location: location(error)},
          events, viewport: page.viewportSize(), captureErrors
        }, null, 2), {mode: 0o600, flag: 'wx'});
      });
      if (captureErrors.length) console.error(`Browser evidence incomplete: ${captureErrors.join(', ')}`);
    },
    async finish() {
      if (tracing) {
        await attempt('trace-discard', () => page.context().tracing.stop());
        tracing = false;
      }
      for (const [event, listener] of listeners) page.off(event, listener);
    }
  };
}
module.exports = {startEvidence};
