const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {startEvidence} = require('../scripts/browser-failure-evidence.cjs');

(async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'zeekr-evidence-test-'));
  try {
    const output = path.join(root, 'missing', 'output');
    const probe = path.join(__dirname, 'fixtures/browser_failure_probe.cjs');
    const run = mode => spawnSync(process.execPath, [probe, mode], {
      env: {...process.env, BROWSER_ARTIFACT_DIR: output, DESKTOP_ONLY: '1'}, encoding: 'utf8', timeout: 30000
    });
    const success = run('pass');
    assert.equal(success.status, 0, success.stderr);
    assert.equal(fs.existsSync(output), false, 'success creates no evidence directory');
    fs.mkdirSync(output, {recursive: true});
    fs.writeFileSync(path.join(output, 'keep.txt'), 'existing evidence');
    const failure = run('fail');
    assert.equal(failure.status, 1, failure.stderr);
    const dirs = fs.readdirSync(output).filter(name => name !== 'keep.txt');
    assert.equal(dirs.length, 1);
    assert.match(dirs[0], /^synthetic-assertion-/);
    const directory = path.join(output, dirs[0]);
    const diagnostic = JSON.parse(fs.readFileSync(path.join(directory, 'diagnostic.json')));
    assert.equal(diagnostic.testId, 'synthetic-assertion');
    assert.equal(diagnostic.error.name, 'AssertionError');
    assert.equal(diagnostic.error.location.file, 'tests/fixtures/browser_failure_probe.cjs');
    assert.ok(diagnostic.error.location.line > 0);
    assert.ok(diagnostic.events.console >= 1);
    assert.equal(diagnostic.events.pageerror, 1);
    assert.equal(diagnostic.events.requestfailed, 1);
    assert.equal(diagnostic.captureErrors.length, 0);
    assert.equal(fs.readFileSync(path.join(directory, 'page.png')).subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    assert.equal(fs.readFileSync(path.join(directory, 'trace.zip')).subarray(0, 2).toString(), 'PK');
    assert.equal(fs.readFileSync(path.join(output, 'keep.txt'), 'utf8'), 'existing evidence');
    assert.ok(!JSON.stringify(diagnostic).includes('DO_NOT_RECORD'));
    const {chromium} = require('playwright');
    const browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
    try {
      const page = await browser.newPage({viewport: {width: 1280, height: 900}});
      const screenshot = fs.readFileSync(path.join(directory, 'page.png')).toString('base64');
      await page.setContent(`<img src="data:image/png;base64,${screenshot}">`);
      assert.deepEqual(await page.locator('img').evaluate(async image => {
        await image.decode(); return {width: image.naturalWidth, height: image.naturalHeight};
      }), {width: 1280, height: 900});
      const archive = spawnSync('python3', ['-c',
        'import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); assert z.testzip() is None; traces=[n for n in z.namelist() if n.endswith(".trace")]; assert traces; [json.loads(line) for n in traces for line in z.read(n).splitlines() if line]',
        path.join(directory, 'trace.zip')], {encoding: 'utf8'});
      assert.equal(archive.status, 0, archive.stderr);
      await assert.rejects(startEvidence(page, {testId: '../escape', synthetic: false}), /synthetic/);
      const recorder = await startEvidence(page, {testId: '../escape', synthetic: true, outputDir: path.join(root, 'custom')});
      await recorder.fail(Error('DO_NOT_RECORD'));
      await recorder.finish();
      assert.equal(fs.readdirSync(path.join(root, 'custom')).length, 1);
      // A file at the configured output path must never be removed or truncate existing data.
      const blocked = path.join(root, 'blocked');
      fs.writeFileSync(blocked, 'keep');
      const broken = await startEvidence(page, {testId: 'blocked', synthetic: true, outputDir: blocked});
      await broken.fail(Error('original failure'));
      await broken.finish();
      assert.equal(fs.readFileSync(blocked, 'utf8'), 'keep');
      const {EventEmitter} = require('node:events');
      const fake = new EventEmitter();
      fake.viewportSize = () => ({width: 1280, height: 900});
      fake.screenshot = async ({path: file}) => fs.writeFileSync(file, Buffer.alloc(8 * 1024 * 1024 + 1));
      const oversized = await startEvidence(fake, {testId: 'oversize', synthetic: true, outputDir: path.join(root, 'limits')});
      fake.emit('console', 'DO_NOT_RECORD');
      await oversized.fail(Error('DO_NOT_RECORD'));
      await oversized.finish();
      const limited = path.join(root, 'limits', fs.readdirSync(path.join(root, 'limits'))[0]);
      assert.equal(fs.existsSync(path.join(limited, 'page.png')), false);
      const limitedText = fs.readFileSync(path.join(limited, 'diagnostic.json'), 'utf8');
      assert.ok(!limitedText.includes('DO_NOT_RECORD'));
      assert.deepEqual(JSON.parse(limitedText).captureErrors, ['page.png-size-limit']);
      fake.screenshot = async () => {throw Error('DO_NOT_RECORD');};
      const unavailable = await startEvidence(fake, {testId: 'unavailable', synthetic: true, outputDir: path.join(root, 'capture-error')});
      await unavailable.fail(Error('original'));
      await unavailable.finish();
      const unavailableDir = path.join(root, 'capture-error', fs.readdirSync(path.join(root, 'capture-error'))[0]);
      assert.deepEqual(JSON.parse(fs.readFileSync(path.join(unavailableDir, 'diagnostic.json'))).captureErrors, ['screenshot']);
      fake.context = () => ({tracing: {
        start: async () => {},
        stop: async ({path: file} = {}) => {if(file)fs.writeFileSync(file, Buffer.alloc(16 * 1024 * 1024 + 1));}
      }});
      const largeTrace = await startEvidence(fake, {testId: 'large-trace', synthetic: true, trace: true, reviewedTrace: true, outputDir: path.join(root, 'trace-limit')});
      await largeTrace.fail(Error('original'));
      await largeTrace.finish();
      const traceDir = path.join(root, 'trace-limit', fs.readdirSync(path.join(root, 'trace-limit'))[0]);
      assert.equal(fs.existsSync(path.join(traceDir, 'trace.zip')), false);
      assert.deepEqual(JSON.parse(fs.readFileSync(path.join(traceDir, 'diagnostic.json'))).captureErrors, ['screenshot', 'trace.zip-size-limit']);
      await assert.rejects(startEvidence(page, {testId: 'trace', synthetic: true, trace: true}), /reviewedTrace/);
    } finally { await browser.close(); }
    console.log('PASS browser evidence: failure exit, readable PNG/ZIP/JSON, success silence, configured/missing output, safe cleanup, privacy gates');
  } finally { fs.rmSync(root, {recursive: true, force: true}); }
})().catch(error => {console.error(error); process.exitCode = 1;});
