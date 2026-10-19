// Reviewed synthetic-only page: no accounts, positions, credentials, or response bodies.
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const {startEvidence} = require('../../scripts/browser-failure-evidence.cjs');
(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
  let recorder;
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 900}});
    recorder = await startEvidence(page, {testId: 'synthetic-assertion', synthetic: true, trace: true, reviewedTrace: true});
    await page.route('**/*', route => route.abort());
    await page.setContent('<h1>Synthetic desktop assertion fixture</h1>');
    const observed = Promise.all(['console', 'pageerror', 'requestfailed'].map(event => page.waitForEvent(event)));
    await page.evaluate(() => { console.log('synthetic console'); setTimeout(() => { throw Error('synthetic page error'); }); fetch('https://synthetic.invalid/unavailable').catch(() => {}); });
    await observed;
    assert.equal(await page.locator('h1').innerText(), process.argv[2] === 'fail' ? 'intentional mismatch' : 'Synthetic desktop assertion fixture');
  } catch (error) {
    if (recorder) await recorder.fail(error);
    throw error;
  } finally {
    if (recorder) await recorder.finish();
    await browser.close();
  }
})().catch(() => { process.exitCode = 1; });
