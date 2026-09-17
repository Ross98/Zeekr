// Desktop vehicle details: synthetic data, temporary storage, no owner session.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const server = spawn('python3', [path.join(__dirname, 'web_fixture.py')]);
  let browser;
  try {
    const port = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(Error('Fixture did not start')), 10000);
      server.stdout.once('data', data => { clearTimeout(timeout); resolve(Number(String(data).trim())); });
      server.once('error', reject);
    });
    browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath:process.env.CHROMIUM_EXECUTABLE} : {})});
    const page = await browser.newPage({viewport:{width:1440,height:1100}});
    const errors = [], external = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (!request.url().startsWith(`http://127.0.0.1:${port}`)) external.push(request.url()); });
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByRole('button', {name:'车辆详情',exact:true}).first().click();
    assert.match(await page.locator('main').innerText(), /尚未读取/);
    await page.getByRole('button', {name:'刷新状态',exact:true}).click();
    await page.getByRole('heading', {name:'门锁、车门与车窗',exact:true}).waitFor();

    // A cached, partially understood vehicle must never read as fully normal.
    assert.equal(await page.locator('.car-summary').count(), 1, 'Details need a first-screen summary with source freshness');
    assert.equal(await page.locator('.car-art svg').count(), 0, 'Use the model photo, not a drawn vehicle');
    const modelPhoto = page.locator('.car-art img');
    await modelPhoto.waitFor();
    assert.match(await modelPhoto.getAttribute('src'), /\.png$/);
    assert.equal(await modelPhoto.evaluate(image => image.complete && image.naturalWidth > 0), true, 'The local model photo loads');
    assert.match(await page.locator('.car-summary').innerText(), /车辆数据更新于.*20 分钟前/);
    assert.match(await page.locator('.car-summary').innerText(), /未知 1 项/);
    assert.doesNotMatch(await page.locator('.car-summary').innerText(), /全部正常/);
    const knownCountColor = await page.locator('.car-summary-stats strong').first().evaluate(node => getComputedStyle(node).color);
    assert.match(await page.locator('.car-cabin').innerText(), /温度更新于.*2 小时/);
    assert.doesNotMatch(await page.locator('.car-tyres').innerText(), /25\.6°C|23\.1°C/);
    assert.doesNotMatch(await page.locator('main').innerText(), /原值|additionalVehicleStatus|sunroofPos/);
    fs.mkdirSync('/tmp/zeekr-car-qa', {recursive:true});
    await page.evaluate(() => { document.querySelector('.breadcrumb').textContent = '车辆详情验收 · 合成数据'; document.querySelector('#toast').hidden=true; window.scrollTo(0,0); });
    await page.screenshot({path:'/tmp/zeekr-car-qa/default-1440.png',fullPage:true});

    const original = await page.evaluate(() => fetch('/api/state').then(r => r.json()));
    // Exercise the presentation boundary with distinct wheel values and all semantic states.
    // These labels are synthetic; this does not validate any new cloud enum.
    const mixed = structuredClone(original);
    mixed.model.doors[0].door = '打开';
    mixed.model.doors[0].window = '未知';
    mixed.model.doors[1].lock = '未锁';
    mixed.model.lock = {value:'未知',confirmed:false};
    mixed.model.tyres.forEach((tyre, i) => {
      tyre.pressure = `${251.125 + i * 10} kPa`;
      tyre.pressure_value = 251.125 + i * 10;
      tyre.temperature = `${21 + i}°C`;
    });
    await page.route('**/api/state', route => route.fulfill({json:mixed}));
    await page.reload();
    await page.getByRole('button', {name:'车辆详情',exact:true}).first().click();
    assert.match(await page.locator('.car-summary').innerText(), /需关注 2 项/);
    assert.match(await page.locator('.car-summary').innerText(), /未知 3 项/);
    assert.match(await page.locator('.car-summary').innerText(), /左前车门.*打开/);
    assert.match(await page.locator('.car-summary').innerText(), /右前门锁.*未锁/);
    const leftFront = page.locator('.car-door[data-position="左前"]');
    assert.equal(await leftFront.locator('.state-attention').count(), 1);
    assert.equal(await leftFront.locator('.state-unknown').count(), 1);
    assert.equal(await leftFront.locator('.state-safe').count(), 1);
    const stateColors = await leftFront.locator('.car-state').evaluateAll(nodes => nodes.map(node => getComputedStyle(node).color));
    assert.equal(new Set(stateColors).size, 3, 'Open, closed and unknown must look different');
    for (const [position, pressure, temperature] of [['左前','251.125 kPa','21°C'],['右前','261.125 kPa','22°C'],['左后','271.125 kPa','23°C'],['右后','281.125 kPa','24°C']]) {
      const wheel = page.locator(`.car-wheel[data-position="${position}"]`);
      assert.match(await wheel.innerText(), new RegExp(pressure.replace('.', '\\.')));
      assert.ok((await wheel.innerText()).includes(temperature));
    }

    // Details are hidden by default but retain original values and keyboard access.
    const rawSummary = page.locator('details[data-detail="closures"] > summary');
    await rawSummary.focus();
    await page.keyboard.press('Enter');
    assert.match(await page.locator('details[data-detail="closures"]').innerText(), /左前车门.*0/s);
    await page.locator('details[data-detail="equipment"] > summary').click();
    assert.match(await page.locator('details[data-detail="equipment"]').innerText(), /天窗位置.*sunroofPos.*101/s);
    assert.match(await page.locator('details[data-detail="equipment"]').innerText(), /待核实/);
    await page.locator('details[data-detail="climate"] > summary').click();
    assert.doesNotMatch(await page.locator('details[data-detail="climate"]').innerText(), /车窗|winPos/);
    await page.locator('details[data-detail="climate"] > summary').click();
    await page.route('**/api/refresh', route => route.fulfill({json:mixed}));
    await page.getByRole('button', {name:'刷新状态',exact:true}).click();
    await page.getByRole('button', {name:'刷新状态',exact:true}).waitFor();
    assert.equal(await page.locator('details[data-detail="closures"]').getAttribute('open'), '');
    await page.locator('details[data-detail="closures"] > summary').click();
    await page.locator('details[data-detail="equipment"] > summary').click();

    fs.mkdirSync('/tmp/zeekr-car-qa', {recursive:true});
    for (const width of [1440,1280,1024]) {
      await page.setViewportSize({width,height:1100});
      await page.evaluate(() => { document.querySelector('.breadcrumb').textContent = '车辆详情验收 · 合成数据'; document.querySelector('#toast').hidden=true; document.activeElement?.blur(); window.scrollTo(0,0); });
      await page.mouse.move(0,0);
      await page.screenshot({path:`/tmp/zeekr-car-qa/mixed-${width}.png`,fullPage:true});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `Overflow at ${width}`);
      const [lf,rf,lr,rr] = await Promise.all(['左前','右前','左后','右后'].map(position => page.locator(`.car-door[data-position="${position}"]`).boundingBox()));
      assert.ok(lf.x + lf.width <= rf.x && lr.x + lr.width <= rr.x && lf.y < lr.y && rf.y < rr.y, `Door positions at ${width}`);
      const [wlf,wrf,wlr,wrr] = await Promise.all(['左前','右前','左后','右后'].map(position => page.locator(`.car-wheel[data-position="${position}"]`).boundingBox()));
      assert.ok(wlf.x + wlf.width <= wrf.x && wlr.x + wlr.width <= wrr.x && wlf.y < wlr.y && wrf.y < wrr.y, `Wheel positions at ${width}`);
      const summary = await page.locator('.car-summary').boundingBox();
      assert.ok(summary.y + summary.height < 1100, 'Summary fits first screen');
    }

    // Unknown input, including unexpected labels, never turns green or disappears.
    const unknown = structuredClone(original);
    unknown.model.updated_time = null;
    unknown.model.updated_at = '未知';
    unknown.model.temperature_updated_time = null;
    unknown.model.temperature_updated_at = '未知';
    unknown.model.lock = {value:'未知',confirmed:false};
    unknown.model.doors.forEach(door => { door.door='未知';door.lock='未知';door.window='未知'; });
    unknown.model.doors[0].door = '未核实值';
    unknown.model.trunk = '未知';
    unknown.model.hood = '未知';
    await page.unroute('**/api/state');
    await page.route('**/api/state', route => route.fulfill({json:unknown}));
    await page.reload();
    await page.getByRole('button', {name:'车辆详情',exact:true}).first().click();
    assert.match(await page.locator('.car-summary').innerText(), /更新时间未知/);
    assert.match(await page.locator('.car-summary').innerText(), /未知 15 项/);
    assert.equal(await page.locator('.car-summary .state-safe').count(), 0);
    assert.notEqual(await page.locator('.car-summary-stats strong').first().evaluate(node => getComputedStyle(node).color), knownCountColor, 'Unknown counts must not use the confirmed-state color');
    assert.equal(await page.locator('.car-closures .car-state.state-safe, .car-closures .car-part.state-safe').count(), 0);
    assert.match(await page.locator('.car-cabin').innerText(), /更新时间未知/);
    await page.route('**/api/refresh', route => route.fulfill({status:502,json:{error:'合成刷新失败'}}));
    await page.getByRole('button', {name:'刷新状态',exact:true}).click();
    await page.getByText(/合成刷新失败/).first().waitFor();
    assert.match(await page.locator('.car-summary').innerText(), /更新时间未知/);
    assert.match(await page.locator('.car-summary').innerText(), /未知 15 项/);
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    console.log('Vehicle details passed: cached freshness, unknown/attention states, raw data disclosure, wheel/door positions, keyboard, refresh, desktop layouts.');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
  }
})().catch(error => {console.error(error);process.exitCode=1;});
