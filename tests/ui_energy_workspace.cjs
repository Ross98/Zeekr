// Desktop-only synthetic vehicle. Catches historical charts leaking into current
// status, eager history/management reads, and stale responses after tab changes.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
  const server=spawn('python3',[path.join(__dirname,'web_fixture.py')]);let browser;
  try{
    const port=await new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>reject(Error('Fixture timeout')),10000);
      server.stdout.once('data',data=>{clearTimeout(timeout);resolve(Number(String(data).trim()));});
      server.once('error',reject);
    });
    browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(5000);
    const errors=[],reads=[];page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>{if(/\/api\/(events|charging\/manage|charging\/process)/.test(request.url()))reads.push(request.url());});
    let releaseHistory,currentActive=false;
    await page.route('**/api/charging/process?**',async route=>{
      const id=new URL(route.request().url()).searchParams.get('id');
      if(id!=='current'&&releaseHistory===null)await new Promise(resolve=>{releaseHistory=resolve;});
      const active=id==='current'&&currentActive;
      await route.fulfill({json:{session:{id,status:id==='current'?(active?'active':'empty'):'ended',start_time:1704067200000,end_time:1704070800000,start_soc:active?52:40,end_soc:64,power_kw:6.4,mode:'ac',partial:false},series:{id,points:id==='current'&&!active?[]:[{time:1704067200000,soc:active?52:40,power_kw:6.4,segment_id:0},{time:1704070800000,soc:64,power_kw:6.4,segment_id:0}],raw_count:2,has_gaps:false}}});
    });
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByRole('button',{name:'刷新状态',exact:true}).click();
    await page.getByText('64%',{exact:true}).first().waitFor();
    await page.locator('#navigation [data-page="energy"]').click();
    await page.getByRole('tab',{name:'当前状态',exact:true}).waitFor();
    await page.getByRole('heading',{name:'最近一次充电',exact:true}).waitFor();
    fs.mkdirSync('/tmp/zeekr-energy-workspace',{recursive:true});
    await page.evaluate(()=>{document.querySelector('#toast').hidden=true;document.activeElement?.blur();scrollTo(0,0);});
    await page.screenshot({path:'/tmp/zeekr-energy-workspace/idle-light.png',fullPage:true});
    assert.equal(await page.locator('#charge-history').count(),0,'current state does not mount historical query controls');
    assert.equal(await page.locator('#charge-management').count(),0,'current state does not mount management');
    assert.equal(reads.filter(url=>url.includes('/api/events?')||url.includes('/api/charging/manage?')).length,0);
    assert.equal(await page.locator('.energy-current-soc').count(),0,'SOC shown once in the top summary');
    await page.getByRole('button',{name:'查看记录',exact:true}).click();
    await page.getByRole('heading',{name:'充电详情',exact:true}).waitFor();
    assert.equal(await page.getByRole('tab',{name:'充电记录',exact:true}).getAttribute('aria-selected'),'true');
    assert.match(await page.locator('#charge-detail').innerText(),/40.*64/s);
    await page.locator('.charging-process-title').getByText('历史详情',{exact:true}).waitFor();
    await page.locator('[data-action="charge-select"]').first().click();
    await page.locator('.charging-charts').waitFor();
    let releaseList;
    const heldList=async route=>{await new Promise(resolve=>{releaseList=resolve;});await route.fallback();};
    await page.route('**/api/events?**',heldList);
    const query=page.waitForRequest('**/api/events?**');
    await page.getByRole('button',{name:'查询充电记录',exact:true}).click();await query;
    assert.equal(await page.locator('.energy-record-process').count(),0,'new query removes the previous selection and process together');
    const queried=page.waitForResponse('**/api/events?**');releaseList();await queried;
    await page.unroute('**/api/events?**',heldList);
    await page.getByRole('heading',{name:'充电详情',exact:true}).waitFor();
    await page.locator('.charging-process-title').getByText('历史详情',{exact:true}).waitFor();
    await page.getByRole('tab',{name:'当前状态',exact:true}).click();
    await page.getByRole('heading',{name:'最近一次充电',exact:true}).waitFor();
    assert.equal(await page.locator('.charging-charts').count(),0,'returning current state never displays selected historical chart');
    assert.equal(new URL(reads.filter(url=>url.includes('/api/charging/process?')).at(-1)).searchParams.get('id'),'current');
    // Hold a historical response, then return to current before it completes.
    releaseHistory=null;
    await page.getByRole('tab',{name:'充电记录',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.charge-loading'));
    await page.getByRole('tab',{name:'当前状态',exact:true}).click();
    await page.getByRole('heading',{name:'最近一次充电',exact:true}).waitFor();
    const oldResponse=page.waitForResponse(response=>response.url().includes('/api/charging/process?')&&new URL(response.url()).searchParams.get('id')!=='current');
    releaseHistory();await oldResponse;releaseHistory=undefined;
    await page.evaluate(()=>new Promise(requestAnimationFrame));
    assert.equal(await page.locator('.charging-charts').count(),0,'late historical response cannot paint current state');
    await page.getByRole('tab',{name:'能源参数',exact:true}).click();
    assert.equal(await page.locator('#charging-parameters').count(),1);
    assert.equal(await page.locator('.energy-details').count(),1);
    await page.locator('[data-detail="energy-low-voltage"] summary').click();
    await page.evaluate(()=>render());
    assert.equal(await page.locator('[data-detail="energy-low-voltage"]').getAttribute('open'),'');
    await page.getByRole('tab',{name:'充电记录',exact:true}).click();
    assert.equal(await page.locator('#charge-management').count(),0,'management mounts only when requested');
    await page.locator('[data-detail="energy-management"] summary').click();
    await page.getByRole('button',{name:'查询管理充电记录',exact:true}).waitFor();
    assert.equal(reads.filter(url=>url.includes('/api/charging/manage?')).length,0,'opening management keeps query explicit');
    await page.getByRole('button',{name:'查询管理充电记录',exact:true}).click();
    await page.locator('[data-charge-record="fixture-charge"]').waitFor();
    await page.waitForFunction(()=>new URLSearchParams(location.search).get('energyTab')==='records');
    await page.reload();
    await page.getByRole('tab',{name:'充电记录',exact:true}).waitFor();
    assert.equal(await page.getByRole('tab',{name:'充电记录',exact:true}).getAttribute('aria-selected'),'true','reload keeps the selected workspace tab');
    // A real current process remains available after the reorganization.
    currentActive=true;
    await page.getByRole('tab',{name:'当前状态',exact:true}).click();
    await page.locator('.charging-charts').waitFor();
    assert.match(await page.locator('.charging-tab-panel').innerText(),/本次观测.*52%.*64%/s);
    assert.equal(await page.getByRole('heading',{name:'最近一次充电',exact:true}).count(),0,'active process keeps past summary in records');
    fs.mkdirSync('/tmp/zeekr-energy-workspace',{recursive:true});
    for(const theme of ['light','dark']){
      await page.getByLabel('外观',{exact:true}).selectOption(theme);
      for(const width of [1440,1280,1024]){
        await page.setViewportSize({width,height:1000});
        for(const name of ['当前状态','充电记录','能源参数']){
          await page.getByRole('tab',{name,exact:true}).click();
          assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${name} ${theme} ${width} overflows`);
        }
      }
      await page.getByRole('tab',{name:'当前状态',exact:true}).click();
      await page.setViewportSize({width:1440,height:1000});
      await page.screenshot({path:`/tmp/zeekr-energy-workspace/current-${theme}.png`,fullPage:true});
    }
    assert.deepEqual(errors,[]);
    console.log('Energy workspace passed: desktop tabs, recent record, lazy queries, current/history isolation, late response, disclosures and themes.');
  }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
