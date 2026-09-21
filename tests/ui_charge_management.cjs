// Real local APIs, synthetic charging event only. No vehicle or external requests.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');

(async()=>{
  const server=spawn('python3',[path.join(__dirname,'web_fixture.py')]);let browser;
  try{
    const port=await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('Fixture timeout')),10000);
      server.stdout.once('data',data=>{clearTimeout(timer);resolve(Number(String(data).trim()));});
      server.stderr.on('data',data=>process.stderr.write(data));server.once('error',reject);
    });
    browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
    const context=await browser.newContext({viewport:{width:1440,height:1080},timezoneId:'Asia/Shanghai'});
    const page=await context.newPage();page.setDefaultTimeout(7000);
    const errors=[];page.on('pageerror',error=>{errors.push(error.message);process.stderr.write(`pageerror: ${error.message}\n`);});
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByRole('button',{name:'刷新状态',exact:true}).click();
    await page.getByText('64%',{exact:true}).first().waitFor();
    await page.getByRole('button',{name:'能源与充电',exact:true}).click();
    await page.getByRole('heading',{name:'管理充电记录',exact:true}).waitFor();
    const record=page.locator('[data-charge-record="fixture-charge"]');
    await record.waitFor();await record.check();
    await page.getByRole('button',{name:'预览移入回收区',exact:true}).click();
    await page.getByRole('heading',{name:'确认移入回收区 1 条充电记录',exact:true}).waitFor();
    await page.getByRole('button',{name:'确认移入回收区',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('[data-charge-record="fixture-charge"]').length===0);
    assert.equal(await page.locator('[data-event-id="fixture-charge"]').count(),0,'Deleted event leaves charging history');
    await page.getByLabel('记录状态').selectOption('trash');
    await record.waitFor();await record.check();
    await page.getByRole('button',{name:'预览恢复',exact:true}).click();
    await page.getByRole('button',{name:'确认恢复',exact:true}).click();
    await page.locator('[data-event-id="fixture-charge"]').waitFor();
    for(const width of [390,320]){
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,`No overflow at ${width}`);
    }
    assert.deepEqual(errors,[]);
    console.log('Charge management browser: trash, exclusion, restore and mobile passed.');
  }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
