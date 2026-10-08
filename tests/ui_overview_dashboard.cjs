const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{const f=await fixture({demo:true,partialCharge:true}),{page}=f;try{
const context=await page.evaluate(()=>state.insights_context);
const date=await page.evaluate(()=>beijingDate(Date.now()));
const original=await page.evaluate(date=>fetch('/api/insights/report?period=month&date='+date).then(r=>r.json()),date);
let report={...original,context,current:{...original.current,days:[{date,distance_km:8.4,trip_count:1,partial_trip_count:1}],events:original.current.events},previous:original.previous};
let ledger={context,totals:{actual_cents:0,actual_charge_count:1,life_count:0,unknown_charge_count:1,unlinked_charge_count:1}};
await page.route('**/api/insights/report?*',r=>r.fulfill({json:report}));await page.route('**/api/insights/costs?*',r=>r.fulfill({json:ledger}));
await page.getByRole('button',{name:'总览',exact:true}).first().click();
// The fixture's first overview query may still be polling when mocks are installed.
// Let that coalesced request settle, then explicitly read the mocked totals.
await page.waitForFunction(()=>!document.querySelector('#overview-records')?.textContent.includes('正在读取已保存记录'));
await page.getByRole('button',{name:'重新读取记录汇总',exact:true}).click();
await page.waitForFunction(()=>document.querySelector('#overview-today-value')?.textContent==='8.4');
assert.equal(await page.locator('#overview-cost-value').innerText(),'0');assert.match(await page.locator('#overview-cost-note').innerText(),/2 项充电待补/);assert.match(await page.locator('#overview-today-note').innerText(),/片段/);
const trip=original.current.events.concat(original.previous.events).find(e=>e.kind==='trip_end');
if(trip){await page.locator(`[data-overview-record="${trip.id}"]`).click();await page.waitForFunction(id=>localTrips?.selected?.id===id,trip.id);assert.ok((await page.locator('#local-trip-facts').innerText()).includes(`里程 ${trip.distance_km} km`),'selected overview trip retains its observed distance');await page.getByRole('button',{name:'← 返回总览原位置',exact:true}).click();}
const charge=original.current.events.concat(original.previous.events).find(e=>e.kind==='charge_end');
if(charge){await page.locator(`[data-overview-record="${charge.id}"]`).click();await page.waitForFunction(id=>chargeSelected?.id===id,charge.id);await page.locator('#charge-detail').waitFor();await page.getByRole('button',{name:'← 返回总览原位置',exact:true}).click();}
await page.locator('#overview-record-filter').selectOption('charge_end');
await page.getByRole('button',{name:'30 天',exact:true}).click();assert.equal(await page.locator('.overview-day').count(),30);assert.ok(await page.locator('.overview-gap').count());
await page.evaluate(()=>scrollTo(0,700));
// Save the actual click position after the approved map/records group swap.
await page.getByRole('button',{name:'去补账',exact:true}).scrollIntoViewIfNeeded();
const scroll=await page.evaluate(()=>scrollY);
await page.getByRole('button',{name:'去补账',exact:true}).click();await page.getByRole('button',{name:'← 返回总览原位置',exact:true}).click();assert.equal(await page.locator('#overview-record-filter').inputValue(),'charge_end');assert.ok(Math.abs(await page.evaluate(()=>scrollY)-scroll)<2);
for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);for(const width of [1440,1280,1024]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width} overflow`);}}
await page.setViewportSize({width:1440,height:1000});await page.locator('#overview-record-filter').selectOption('all');await page.getByLabel('外观',{exact:true}).selectOption('light');await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:'/tmp/zeekr-overview-production-desktop.png',fullPage:true});
report={...report,context:'other-vehicle'};ledger={...ledger,context:'other-vehicle'};await page.getByRole('button',{name:'重新读取记录汇总',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#overview-today-value').textContent==='未知');assert.equal(await page.locator('#overview-cost-value').innerText(),'未知');assert.match(await page.locator('#overview-records').innerText(),/读取失败/);
assert.deepEqual(f.errors,[]);assert.equal(f.external.length,0);console.log('PASS overview actual-only zero, partial distance, 30-day missing samples, return/filter/scroll, context rejection, 6 desktop viewport/theme checks');
}finally{await f.close();}})().catch(e=>{console.error(e);process.exit(1)});
