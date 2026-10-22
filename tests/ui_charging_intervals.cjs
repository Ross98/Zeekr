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
  assert.match(await metric.innerText(),/综合电耗.*16\.65.*kWh\/100 km/s);
  assert.deepEqual(await page.locator('.cr-analysis-metrics>div').evaluateAll(ns=>ns.map(n=>n.querySelectorAll('p').length)),[1,1,1,1]);
  assert.match(await metric.innerText(),/3 个有效区间.*310 km/s);
  const cost=page.locator('[data-interval-cost]');
  assert.equal(await cost.count(),1);
  assert.match(await cost.innerText(),/百公里参考电费.*11\.47.*元\/100 km/s);
  assert.match(await cost.innerText(),/按区间电价估算/);
  await page.locator('[data-analysis-details]>summary').click();
  const evidence=await page.locator('[data-analysis-details]').innerText();
  assert.match(evidence,/纳入 3 \/ 4 个区间/);assert.match(evidence,/310 km.*51\.6 kWh/s);
  assert.match(evidence,/1 个参考端点区间/);assert.match(evidence,/计价区间/);
  await page.locator('[data-analysis-details]>summary').click();
  assert.doesNotMatch(await metric.innerText(),/参考电费 11/);
  await page.locator('[data-detail=charging-intervals]>summary').click();
  const rows=page.locator('[data-charge-interval]');assert.equal(await rows.count(),4);
  assert.match(await page.locator('[data-charge-interval=interval-b]').innerText(),/08\/31.*09\/02.*跨月.*200 km.*34\.4 kWh/s);
  assert.match(await page.locator('[data-charge-interval=interval-c]').innerText(),/参考电费 0\.00 元/);
  assert.match(await page.locator('[data-charge-interval=interval-late]').innerText(),/09\/11 07:59/);
  assert.match(await page.locator('[data-charge-interval=interval-late]').innerText(),/充电前上一段状态.*1 分钟.*未计入/s);
  await page.evaluate(()=>render());
  assert.equal(await page.locator('[data-detail=charging-intervals]').getAttribute('open'),'');
  fs.mkdirSync('/tmp/zeekr-charging-intervals',{recursive:true});
  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   for(const width of [1024,1280,1440]){
    await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.equal(await page.locator('.cr-analysis-metrics>div').count(),4);
    const fontSizes=await page.locator('.cr-analysis-metrics>div>.cr-analysis-value').evaluateAll(ns=>ns.map(n=>getComputedStyle(n).fontSize));assert.equal(new Set(fontSizes).size,1);
    await contrast(page,'#charging-review');
   }
   await page.screenshot({path:`/tmp/zeekr-charging-intervals/${theme}.png`,fullPage:true});
  }
  await page.getByLabel('充电月份',{exact:true}).fill('2026-06');
  await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2026-06');
  assert.match(await metric.innerText(),/样本不足/);
  assert.doesNotMatch(await metric.innerText(),/0 元/);
  assert.match(await cost.innerText(),/样本不足/);assert.doesNotMatch(await cost.innerText(),/0.00/);
  assert.deepEqual(f.errors,[]);
  console.log('CHARGING_INTERVALS_BROWSER_PASS: weighted consumption, cross-month, late starts, free reference fees, disclosures, empty months and desktop contrast');
 }catch(error){await f.fail(error);throw error;}finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
