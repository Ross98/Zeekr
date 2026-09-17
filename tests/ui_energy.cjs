// Synthetic state only; catches snapshot fallback, missing trip states and disclosure loss.
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
    const page = await browser.newPage({viewport:{width:1440,height:1050}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
    assert.match(await page.locator('main').innerText(), /尚未读取/);
    await page.getByRole('button',{name:'刷新状态',exact:true}).click();
    await page.getByText('64%',{exact:true}).first().waitFor();
    const original = await page.evaluate(() => fetch('/api/state').then(r=>r.json()));
    const data = structuredClone(original);
    data.profile = {name:'验收车辆',variant:'合成数据',range_km:546,range_standard:'CLTC',range_source:'合成配置'};
    data.model.metric_details.battery.value = 50;
    data.model.metric_details.range.value = 230;
    data.model.metrics.battery = '50%';
    data.model.metrics.range = '230 km';
    data.range_attainment = {status:'available', ratio:73.26007326, distance_km:80, start_soc:80, end_soc:60, used_soc:20, reference_km:109.2, standard:'CLTC', start_at:'2024-01-01 08:00',end_at:'2024-01-01 09:00'};
    await page.route('**/api/state', route=>route.fulfill({json:data}));
    await page.route('**/api/refresh', route=>route.fulfill({json:data}));
    const refresh = async () => {
      await page.getByRole('button',{name:'刷新状态',exact:true}).click();
      await page.waitForFunction(() => !document.querySelector('[data-action="refresh"]').disabled);
    };
    await refresh();
    assert.match(await page.locator('main').innerText(), /73\.3/,'80 km driven on 20 percentage points must use trip attainment');
    assert.match(await page.locator('.energy-rating').innerText(), /546/);
    assert.match(await page.locator('.energy-rating').innerText(), /CLTC/);
    assert.match(await page.locator('.energy-charge').innerText(), /暂无有效时间估计/);
    assert.doesNotMatch(await page.locator('main').innerText(), /chargeUAct|mainBatteryStatus/);
    const details = page.locator('details[data-detail="energy-electric"]');
    await details.locator('summary').focus();
    await page.keyboard.press('Enter');
    assert.match(await details.innerText(), /chargeUAct/);
    await refresh();
    assert.equal(await details.getAttribute('open'), '');
    await details.locator('summary').click();
    fs.mkdirSync('/tmp/zeekr-energy-qa',{recursive:true});
    for (const width of [1440,1024,390,320]) {
      await page.setViewportSize({width,height:1050});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true,`Overflow at ${width}`);
      await page.evaluate(()=>{document.querySelector('#toast').hidden=true; document.activeElement?.blur(); window.scrollTo(0,0);});
      await page.screenshot({path:`/tmp/zeekr-energy-qa/energy-${width}.png`,fullPage:true});
    }
    await page.locator('details[data-detail="energy-low-voltage"] > summary').click();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true,'Expanded low-voltage fields fit mobile');
    await page.setViewportSize({width:1440,height:1050});
    // Current snapshot changes must not change an already completed trip.
    data.model.metric_details.battery.value=0;
    data.model.metric_details.range.value=null;
    await refresh();
    assert.match(await page.locator('.energy-achievement').innerText(), /73\.3/);
    assert.match(await page.locator('.energy-achievement').innerText(), /80.*60/s);
    for (const status of ['no_trip','incomplete','invalid','no_consumption','no_rating','unavailable']) {
      data.range_attainment={status};
      await refresh();
      assert.doesNotMatch(await page.locator('.energy-achievement').innerText(), /73\.3|84\.2|NaN|Infinity/);
      assert.match(await page.locator('.energy-achievement').innerText(), /暂无可计算行程|无法计算/);
    }
    delete data.range_attainment;
    await refresh();
    assert.match(await page.locator('.energy-achievement').innerText(), /暂无可计算行程/);
    data.model.charging={value:'未知',confirmed:false};
    await refresh();
    assert.match(await page.locator('.energy-charge').innerText(),/充电状态未知/);
    assert.doesNotMatch(await page.locator('.energy-charge').innerText(),/未插枪/);
    assert.deepEqual(errors,[]);
    console.log('Energy UI passed: trip attainment, snapshot independence, missing/invalid trips, unknown charging, keyboard, refresh, 4 widths.');
  } finally { if(browser) await browser.close(); server.kill('SIGTERM'); }
})().catch(error=>{console.error(error);process.exitCode=1;});
