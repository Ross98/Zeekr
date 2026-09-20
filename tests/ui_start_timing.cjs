// End-to-end synthetic transitions -> persisted API -> desktop/mobile UI.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
(async()=>{
  const server=spawn('python3',[path.join(__dirname,'start_timing_fixture.py')]);
  let browser;
  try{
    const port=await new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>reject(Error('Fixture did not start')),10000);
      server.stdout.once('data',data=>{clearTimeout(timeout);resolve(Number(String(data).trim()));});
      server.stderr.on('data',data=>process.stderr.write(data));server.once('error',reject);
    });
    browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
    const page=await browser.newPage({viewport:{width:1440,height:1080},timezoneId:'America/Los_Angeles'});
    page.setDefaultTimeout(8000);
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();
    await page.getByLabel('轨迹日期').fill('2024-01-01');
    await page.locator('[data-local-trip]').filter({hasText:'08:00'}).click();
    const trip=page.locator('#local-trip-detail .start-evidence');
    await trip.getByText('起点证据：相邻观测圈定范围',{exact:true}).waitFor();
    assert.match(await trip.innerText(),/08:00:00.*08:01:00/s);
    assert.match(await trip.innerText(),/系统首次发现.*08:01:20.*首次样本年龄.*20 秒.*发现延迟范围.*20 秒 ～ 80 秒/s);
    assert.doesNotMatch(await page.locator('#local-trip-detail').innerText(),/实际开始时间.*08:00:00/);
    fs.mkdirSync('/tmp/zeekr-start-timing-qa',{recursive:true});
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1100});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`Trip overflow ${width}`);
      await page.screenshot({path:`/tmp/zeekr-start-timing-qa/trip-${width}.png`,fullPage:true});
    }
    await page.getByLabel('轨迹日期').fill('2024-01-02');
    await page.locator('[data-local-trip="legacy-trip"]').click();
    await page.getByText('起点证据：历史证据缺失',{exact:true}).waitFor();
    assert.match(await page.locator('#local-trip-detail').innerText(),/实际开始时间未知/);
    await page.setViewportSize({width:1440,height:1100});
    await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
    const processPanel=page.locator('.charging-tab-panel');
    await processPanel.getByText('起点证据：首次看到时已开始',{exact:true}).waitFor();
    assert.match(await processPanel.locator('.start-evidence').first().innerText(),/08:20:00.*08:20:25.*至少 25 秒，上限未知/s);
    await page.getByLabel('充电记录日期').fill('2024-01-01');
    await page.getByRole('button',{name:/查看充电记录 1/}).click();
    await page.locator('#charge-detail .start-evidence').getByText('起点证据：相邻观测圈定范围',{exact:true}).waitFor();
    assert.match(await page.locator('#charge-detail').innerText(),/记录起点.*08:13.*可能开始范围.*08:12:00.*08:13:00/s);
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1100});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`Charge overflow ${width}`);
      await page.screenshot({path:`/tmp/zeekr-start-timing-qa/charge-${width}.png`,fullPage:true});
    }
    assert.deepEqual(errors,[]);
    console.log('START_TIMING_UI_PASS');
  }finally{await browser?.close();server.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
