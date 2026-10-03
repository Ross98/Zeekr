// Desktop overview acceptance. Synthetic gateway and temporary storage only.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async()=>{
  const server=spawn('python3',['tests/web_fixture.py']); let browser;
  try {
    const port=await new Promise((resolve,reject)=>{server.stdout.once('data',d=>resolve(Number(String(d).trim())));server.once('error',reject)});
    browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];const external=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith(`http://127.0.0.1:${port}`))external.push(r.url())});
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByRole('button',{name:'刷新状态',exact:true}).click();
    await page.getByText('64%',{exact:true}).first().waitFor();
    assert.doesNotMatch(await page.locator('.hero').innerText(),/中国国内版|未选装空气悬架|仅有电吸门/);
    assert.match(await page.locator('.hero').innerText(),/车辆数据更新于.*20 分钟前/);
    assert.match(await page.locator('.closure-summary').innerText(),/车门关闭.*车窗关闭.*尾门关闭/s);
    assert.match(await page.locator('main').innerText(),/后台未在线/);
    await page.locator('[data-detail="overview-latest"] summary').click();
    assert.match(await page.locator('.recent-events').innerText(),/最近完成行程.*8\.4 km.*70%.*68%/s);
    assert.match(await page.locator('.recent-events').innerText(),/最近完成充电.*40%.*64%/s);
    assert.match(await page.locator('.tyre-grid').innerText(),/265\.1 kPa/);
    assert.doesNotMatch(await page.locator('.tyre-grid').innerText(),/265\.125/);
    await page.getByRole('button',{name:'车辆',exact:true}).first().click();
    await page.getByRole('button',{name:'状态总览',exact:true}).click();
    assert.match(await page.locator('.tyre-grid').innerText(),/265\.125 kPa/);
    await page.getByRole('button',{name:'总览',exact:true}).click();
    await page.locator('.data-explanation summary').click();
    assert.match(await page.locator('.data-explanation').innerText(),/动力电池专用字段/);
    await page.locator('.data-explanation summary').click();
    fs.mkdirSync('/tmp/zeekr-overview-qa',{recursive:true});
    for(const width of [1440,1280,1024]) {
      await page.setViewportSize({width,height:1000});
      await page.evaluate(()=>{document.querySelector('#toast').hidden=true});
      await page.screenshot({path:`/tmp/zeekr-overview-qa/desktop-${width}.png`,fullPage:true});
      const boxes=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,copy:document.querySelector('.hero-copy').getBoundingClientRect().toJSON(),art:document.querySelector('.hero-car').getBoundingClientRect().toJSON()}));
      assert.equal(boxes.overflow,false,`overflow at ${width}`);
      assert.ok(boxes.copy.right<=boxes.art.left+1 || boxes.copy.bottom<=boxes.art.top+1,`hero overlaps at ${width}`);
    }
    const original=await page.evaluate(()=>fetch('/api/state').then(r=>r.json()));
    for(const [result,text] of [['cached','复用本机缓存'],['unchanged','车辆数据未更新'],['new','获得新车辆数据'],['time_unknown','更新时间未知']]){
      await page.route('**/api/refresh',r=>r.fulfill({json:{...original,refresh_result:result}}));
      await page.getByRole('button',{name:'刷新状态',exact:true}).click();
      await page.getByText(text,{exact:false}).first().waitFor();
      await page.unroute('**/api/refresh');
    }
    // Countdown blocks a repeated gateway refresh, then restores the action.
    await page.route('**/api/state',r=>r.fulfill({json:{...original,next_query_at:Date.now()/1000+3}}));
    await page.reload();
    await page.getByRole('button',{name:/等待.*秒/}).waitFor();
    assert.equal(await page.getByRole('button',{name:/等待.*秒/}).isDisabled(),true);
    await page.unroute('**/api/state');
    await page.getByRole('button',{name:'刷新状态',exact:true}).waitFor();
    // Missing fields remain unknown, never normal/closed or a zero battery.
    const unknown=structuredClone(original);
    unknown.model.updated_time=null;unknown.model.updated_at='未知';unknown.model.metrics.battery='未知';unknown.model.metric_details.battery.value=null;
    unknown.model.lock={value:'未知',confirmed:false};unknown.model.charging={value:'未知',confirmed:false};
    unknown.model.closure={doors:'未知',windows:'未知',trunk:'未知'};
    await page.route('**/api/state',r=>r.fulfill({json:unknown}));await page.reload();
    await page.getByText('车门未知',{exact:true}).waitFor();
    assert.match(await page.locator('.hero').innerText(),/更新时间未知/);
    assert.equal(await page.locator('.hero-state .good').count(),0);
    assert.match(await page.locator('.overview-metrics').innerText(),/未知/);
    await page.unroute('**/api/state');await page.reload();await page.getByText('64%',{exact:true}).first().waitFor();
    // Background failures preserve data and recover without refreshing the cloud.
    await page.route('**/api/state',r=>r.abort());
    await page.locator('#local-connection').getByText('本机服务已断开',{exact:true}).waitFor({timeout:16000});
    assert.match(await page.locator('main').innerText(),/64%/);
    await page.unroute('**/api/state');
    await page.getByRole('button',{name:'重新连接',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#connectivity-notice').hidden);
    // Initial connection failure has a retry path too.
    await page.route('**/api/state',r=>r.abort());await page.reload();
    await page.getByRole('button',{name:'重新连接',exact:true}).waitFor();
    await page.unroute('**/api/state');await page.getByRole('button',{name:'重新连接',exact:true}).click();
    await page.getByText('64%',{exact:true}).first().waitFor();
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    console.log('Desktop overview passed: layouts, timestamps, closure, precision, refresh outcomes, countdown, missing data, offline recovery.');
  }finally{if(browser)await browser.close();server.kill('SIGTERM')}
})().catch(e=>{console.error(e);process.exitCode=1});
