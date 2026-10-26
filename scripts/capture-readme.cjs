// Capture only isolated synthetic fixtures; never connect to a live account.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');
const {fixture}=require('../tests/ui_insight_helpers.cjs');
const output=path.join(__dirname,'../docs/images');
const screenshots=[];
const watermark='html::after{content:"合成数据截图\\A非真实车辆记录";position:fixed;left:24px;bottom:110px;width:176px;box-sizing:border-box;z-index:2147483647;margin:0;padding:10px;border:1px solid #668087;border-radius:8px;background:#19272d;color:#dce8eb;font:12px/1.5 sans-serif;white-space:pre-line;pointer-events:none}';
// Each fresh browser may talk only to its synthetic loopback fixture.
async function isolate(page){
  let origin;
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(!origin&&request.isNavigationRequest()&&url.protocol==='http:'&&url.hostname==='127.0.0.1'&&!['18765','8765'].includes(url.port))origin=url.origin;
    if(url.origin===origin||url.protocol==='data:')return route.continue();
    await route.abort('blockedbyclient');
    throw Error('README capture blocked a request outside its synthetic fixture');
  });
}
async function capture(page,name){
  await page.evaluate(()=>document.fonts.ready);
  // The app can replace body markup while polling. Attach to the document
  // root and also inject at screenshot time, so the disclosure cannot vanish.
  await page.addStyleTag({content:watermark});
  await page.evaluate(()=>{
    document.activeElement?.blur();
    scrollTo(0,0);
  });
  const visible=await page.locator('body').innerText();
  assert.doesNotMatch(visible,/PRIVATE-|NEVER-EXPORT|Bearer\s|eyJ[A-Za-z0-9_-]{15}|1[3-9]\d{9}/,'No credentials, private fixture fields or phone numbers');
  assert.doesNotMatch(visible,/[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][A-Z0-9]{5,6}/,'No visible license plates');
  assert.doesNotMatch(visible,/\b[A-HJ-NPR-Z0-9]{17}\b/,'No visible VIN');
  assert.doesNotMatch(visible,/(?:latitude|longitude)\s*[:：]|\d{2,3}\.\d{6,}/i,'No precise coordinate text');
  assert.ok(!await page.locator('iframe').count(),'No embedded external content');
  assert.match(await page.evaluate(()=>getComputedStyle(document.documentElement,'::after').content),/合成数据截图/,'Synthetic-data disclosure is attached to the document root');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Desktop frame fits');
  await page.screenshot({path:path.join(output,name+'.png'),fullPage:false,style:watermark});screenshots.push(name);
}
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const f=await fixture({demo:true,chargingPlaces:true,initialResearch:false,reportNow:'2026-10-05',beforeGoto:isolate});
 try{
  const {page}=f;await page.setViewportSize({width:1440,height:1500});
  await page.getByLabel('外观',{exact:true}).selectOption('dark');
  await page.getByRole('button',{name:'用车周报',exact:true}).click();
  await page.getByLabel('报告周期',{exact:true}).selectOption('month');
  await page.getByLabel('周期内日期',{exact:true}).fill('2026-09-20');
  await page.getByRole('button',{name:'查看报告',exact:true}).click();
  await page.getByRole('heading',{name:'2026-09-01 — 2026-09-30',exact:true}).waitFor();
  assert.equal(await page.locator('#report-energy-comparison [data-report-metric]').count(),4);
  await capture(page,'usage-report');
  await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
  await page.getByLabel('充电月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2026-09');
  await capture(page,'charging-review');
  await page.getByRole('button',{name:'用车账本',exact:true}).first().click();
  await page.getByRole('button',{name:'费用总览',exact:true}).click();
  await page.locator('#books-month').fill('2026-09');
  await page.getByRole('button',{name:'读取费用总览',exact:true}).click();
  await page.locator('.books-pie').waitFor();
  await page.locator('[data-books-record]').first().waitFor();
  await capture(page,'costs-overview');
  await page.getByRole('button',{name:'充电账本',exact:true}).click();
  await page.getByLabel('账本月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取账本',exact:true}).click();
  await page.locator('[data-ledger-entry]').first().waitFor();
  await page.waitForFunction(()=>document.querySelector('#ledger-load')?.disabled===false&&!document.body.innerText.includes('正在读取账本'));
  await capture(page,'charging-ledger');
  await page.getByRole('button',{name:'生活账本',exact:true}).click();
  await page.locator('.life-category-chart').waitFor();await capture(page,'expense-ledger');
  await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();
  await page.getByRole('button',{name:'行程标签',exact:true}).click();
  await page.getByLabel('标签月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
  await page.locator('.tag-share-strip').waitFor();await capture(page,'trip-tags');
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[],'No third-party requests');
 }finally{await f.close();}
 const server=spawn('python3',[path.join(__dirname,'../tests/recall_fixture.py')]);let browser;
 try{
  const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Recall fixture timeout')),15000);server.stdout.once('data',d=>{clearTimeout(timer);resolve(Number(String(d).trim()));});server.once('error',reject);server.stderr.on('data',d=>process.stderr.write(d));});
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1500}}),errors=[],external=[];
  await isolate(page);
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:'+port)&&!r.url().startsWith('data:'))external.push(r.url());});
  await page.goto('http://127.0.0.1:'+port);await page.getByLabel('外观',{exact:true}).selectOption('dark');
  await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();
  await page.getByLabel('轨迹日期',{exact:true}).fill('2026-09-20');
  await page.getByRole('button',{name:'查询行程',exact:true}).click();await page.locator('.tv-clock').waitFor();
  assert.equal(await page.locator('#local-trip-details-disclosure').evaluate(e=>e.open),false,'No location/map disclosure');
  await capture(page,'local-trips');assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 }finally{if(browser)await browser.close();server.kill();}
 console.log('README_SCREENSHOTS_PASS '+screenshots.join(', '));
})().catch(error=>{console.error(error);process.exitCode=1;});
