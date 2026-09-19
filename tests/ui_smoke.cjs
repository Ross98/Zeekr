// Run with NODE_PATH pointing at a Playwright installation. Uses synthetic data only.
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const server = spawn('python3', [path.join(__dirname, 'web_fixture.py')]);
  let browser;
  try {
    const port = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(Error('Fixture did not start')), 10000);
      server.stdout.once('data', d => { clearTimeout(timeout); resolve(Number(String(d).trim())); });
      server.once('error', reject);
    });
    browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}) });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const external = [];
    page.on('request', request => { if (!request.url().startsWith(`http://127.0.0.1:${port}`)) external.push(request.url()); });
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByRole('heading', { name: '总览', exact: true }).waitFor();
    assert.match(await page.locator('main').innerText(), /尚未读取/);
    await page.getByRole('button', { name: '刷新状态', exact: true }).click();
    await page.getByText('64%', { exact: true }).first().waitFor();
    assert.equal(external.length, 0, 'No external map requests before consent');
    fs.mkdirSync('/tmp/zeekr-web-qa', { recursive: true });
    await page.evaluate(() => { document.querySelector('.breadcrumb').textContent = '界面验收 · 合成数据'; document.querySelector('#toast').hidden=true; });
    await page.screenshot({ path: '/tmp/zeekr-web-qa/desktop.png', fullPage: true });
    await page.getByRole('button', { name: '车辆', exact: true }).first().click();
    for (const side of ['左前', '右前', '左后', '右后']) {
      assert.match(await page.locator('main').innerText(), new RegExp(side));
    }
    await page.getByRole('button', { name: '能源与充电', exact: true }).first().click();
    assert.match(await page.locator('main').innerText(), /暂无有效时间估计/);
    await page.getByRole('button', { name: '参数字典', exact: true }).first().click();
    await page.getByLabel('搜索参数').fill('sunroof');
    assert.match(await page.locator('#field-results').innerText(), /天窗位置/);
    await page.getByRole('button', { name: '定位地图', exact: true }).first().click();
    assert.equal(external.length, 0);
    await page.getByRole('button', { name: '显示位置并加载地图', exact: true }).click();
    await page.getByText('位置未确认', { exact: true }).first().waitFor();
    assert.match(await page.locator('main').innerText(), /定位采集时间未提供/);
    await page.getByRole('button', { name: '隐藏位置', exact: true }).click();
    await page.getByRole('button', { name: '行程与轨迹', exact: true }).first().click();
    await page.getByRole('button', { name: '云端历史', exact: true }).click();
    assert.match(await page.locator('main').innerText(), /需要连接云端历史账号/);
    await page.getByRole('button', { name: '设置', exact: true }).first().click();
    assert.match(await page.locator('main').innerText(), /自适应采样/);
    assert.match(await page.locator('main').innerText(), /后台未在线/);
    await page.getByRole('button', { name: '暂停采集', exact: true }).click();
    await page.getByRole('button', { name: '开始采集', exact: true }).waitFor();
    await page.getByRole('button', { name: '开始采集', exact: true }).click();
    await page.getByRole('button', { name: '暂停采集', exact: true }).waitFor();
    await page.screenshot({ path: '/tmp/zeekr-web-qa/settings-unified.png', fullPage: true });
    await page.getByRole('button', { name: '行程与轨迹', exact: true }).first().click();
    await page.getByRole('button', { name: '本地记录', exact: true }).click();
    // Fixture's cached sample is 20 minutes old; near midnight it belongs to yesterday.
    await page.getByLabel('轨迹日期').fill(await page.evaluate(() => new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(Date.now()-20*60*1000))));
    await page.getByRole('button', { name: '显示位置并加载地图', exact: true }).click();
    await page.getByLabel('轨迹回看位置').waitFor();
    assert.match(await page.locator('#playback-label').innerText(), /缓存状态时间/);
    assert.match(await page.locator('#playback-label').innerText(), /位置未确认/);
    await page.screenshot({ path: '/tmp/zeekr-web-qa/tracks.png', fullPage: true });
    await page.getByRole('button', { name: '总览', exact: true }).first().click();
    await page.route('**/api/refresh', route => route.fulfill({ status: 502, contentType: 'application/json', body: JSON.stringify({error:'合成网络故障'}) }));
    await page.getByRole('button', { name: '刷新状态', exact: true }).click();
    await page.getByText(/合成网络故障/).first().waitFor();
    assert.match(await page.locator('main').innerText(), /64%/);
    await page.unroute('**/api/refresh');
    if (!process.env.DESKTOP_ONLY) {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => { document.querySelector('#toast').hidden=true; });
    await page.screenshot({ path: '/tmp/zeekr-web-qa/mobile.png', fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'No horizontal overflow');
    for (const [key,label] of [['car','车辆'],['map','定位地图'],['tracks','行程与轨迹']]) {
      await page.locator(`#mobile-navigation [data-page="${key}"]`).click();
      await page.getByRole('heading', { name: label, exact: true }).waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Mobile ${key} overflow`);
    }
    for (const key of ['energy','fields','settings']) {
      await page.locator('#mobile-navigation [data-page="more"]').click();
      await page.locator(`main [data-page="${key}"]`).click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Mobile ${key} overflow`);
    }
    }
    assert.deepEqual(errors, []);
    console.log(`Browser smoke passed: desktop${process.env.DESKTOP_ONLY?'':', mobile'}, refresh, details, privacy, map, history, recording, errors.`);
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
