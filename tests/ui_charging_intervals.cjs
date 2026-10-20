const assert=require('node:assert/strict');
const fs=require('node:fs');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture({chargingIntervals:true,initialResearch:false}),{page}=f;
 try{
  await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
  await page.getByLabel('充电月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2026-09');
  const metric=page.locator('[data-interval-metric]');
  assert.match(await metric.innerText(),/综合电耗.*14\.33.*kWh\/100 km/s);
  assert.match(await metric.innerText(),/300 km.*43 kWh/s);
  assert.match(await metric.innerText(),/纳入 2 \/ 4 个区间/);
  assert.match(await metric.innerText(),/参考电费 11\.47 元\/100 km/);
  await page.locator('[data-detail=charging-intervals]>summary').click();
  const rows=page.locator('[data-charge-interval]');assert.equal(await rows.count(),4);
  assert.match(await page.locator('[data-charge-interval=interval-b]').innerText(),/08\/31.*09\/02.*跨月.*200 km.*34\.4 kWh/s);
  assert.match(await page.locator('[data-charge-interval=interval-c]').innerText(),/参考电费 0\.00 元/);
  assert.match(await page.locator('[data-charge-interval=interval-late]').innerText(),/首次观测时已在充电.*未纳入/s);
  await page.evaluate(()=>render());
  assert.equal(await page.locator('[data-detail=charging-intervals]').getAttribute('open'),'');
  fs.mkdirSync('/tmp/zeekr-charging-intervals',{recursive:true});
  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   for(const width of [1024,1280,1440]){
    await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await contrast(page,'#charging-review');
   }
   await page.screenshot({path:`/tmp/zeekr-charging-intervals/${theme}.png`,fullPage:true});
  }
  await page.getByLabel('充电月份',{exact:true}).fill('2026-06');
  await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2026-06');
  assert.match(await metric.innerText(),/样本不足/);
  assert.doesNotMatch(await metric.innerText(),/0 元/);
  assert.deepEqual(f.errors,[]);
  console.log('CHARGING_INTERVALS_BROWSER_PASS: weighted consumption, cross-month, late starts, free reference fees, disclosures, empty months and desktop contrast');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
