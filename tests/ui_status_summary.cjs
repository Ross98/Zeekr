// Desktop-only status summary acceptance. Synthetic vehicle and temporary storage.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
(async()=>{
 const server=spawn('python3',[path.join(__dirname,'web_fixture.py')]);let browser;
 try{
  const port=await new Promise((resolve,reject)=>{server.stdout.once('data',d=>resolve(Number(String(d).trim())));server.once('error',reject)});
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}`);
  await page.getByRole('button',{name:'刷新状态',exact:true}).click();
  await page.getByText('64%',{exact:true}).first().waitFor();
  assert.match(await page.locator('.closure-summary').innerText(),/前舱盖关闭/);
  await page.getByRole('button',{name:'车辆',exact:true}).first().click();
  await page.getByRole('button',{name:'状态总览',exact:true}).click();
  assert.equal(await page.locator('.car-summary-stats>div').count(),6);
  assert.match(await page.locator('.car-summary-stats').innerText(),/全部关闭/);
  assert.match(await page.locator('.car-summary-stats').innerText(),/全部锁止/);
  const original=await page.evaluate(()=>structuredClone(state.model));
  fs.mkdirSync('/tmp/zeekr-status-summary-qa',{recursive:true});
  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   for(const width of [1440,1280,1024]){
    await page.setViewportSize({width,height:1000});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width} overflow`);
    const boxes=await page.locator('.car-main-grid').evaluate(el=>{const box=s=>el.querySelector(s).getBoundingClientRect().toJSON();return {door:box('.car-closures'),tyre:box('.car-tyres'),cabin:box('.car-cabin')};});
    assert.ok(boxes.cabin.top>=Math.max(boxes.door.bottom,boxes.tyre.bottom), 'cabin below both panels');
    if(width===1440){await page.evaluate(()=>{document.querySelector('#toast').hidden=true;document.activeElement?.blur()});await page.screenshot({path:`/tmp/zeekr-status-summary-qa/${theme}.png`,fullPage:true});}
   }
  }
  await page.evaluate(()=>{state.model.doors[0].door='未知';state.model.doors[1].door='打开';state.model.hood='未知';render();});
  assert.match(await page.locator('.car-summary-stats').innerText(),/2 项关闭 · 1 项打开 · 1 项未知/);
  assert.match(await page.locator('.car-summary-counts').innerText(),/需关注 1 项.*未知 2 项/s);
  assert.equal(await page.locator('.car-summary-stats>div').first().locator('.state-safe').count(),0);
  await page.locator('.car-pending summary').click();
  await page.getByRole('button',{name:'前舱盖 · 未知',exact:true}).click();
  assert.equal(await page.evaluate(()=>document.activeElement.id),'car-hood');
  await page.evaluate(model=>{state.model=model;render();},original);
  assert.deepEqual(errors,[]);
  console.log('DESKTOP_STATUS_SUMMARY_PASS: six groups, mixed states, detail focus, six theme/width layouts');
 }finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
