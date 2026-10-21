const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{const f=await fixture({evidenceTestId:'ui_overview_dashboard',demo:true,partialCharge:true}),{page}=f;try{
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
if(trip){
await page.locator(`[data-overview-record="${trip.id}"]`).click();
await page.waitForFunction(id=>localTrips?.selected?.id===id,trip.id);
await page.locator('#local-trip-details-disclosure>summary').click();
const distance=page.locator('#local-trip-facts p').filter({hasText:' · 里程 '});
await distance.waitFor({state:'visible'});
assert.ok((await distance.innerText()).endsWith(` · 里程 ${trip.distance_km} km`),'selected overview trip retains its observed distance');
await page.getByRole('button',{name:'← 返回总览原位置',exact:true}).click();
}
const charge=original.current.events.concat(original.previous.events).find(e=>e.kind==='charge_end');
if(charge){await page.locator(`[data-overview-record="${charge.id}"]`).click();await page.waitForFunction(id=>chargeSelected?.id===id,charge.id);await page.locator('#charge-detail').waitFor();await page.getByRole('button',{name:'← 返回总览原位置',exact:true}).click();}
await page.locator('#overview-record-filter').selectOption('charge_end');
// Catch lost calendar navigation, stale door selection and duplicated homepage sections.
assert.equal(await page.locator('.overview-power').count(),1,'battery and estimated range share one card');
assert.equal(await page.locator('.overview-metrics>.metric').count(),2);
assert.equal(await page.locator('.hero .overview-power').count(),1,'power fills the middle of the hero');
assert.equal(await page.locator('.overview-metrics .overview-power').count(),0,'no repeated power card below');
assert.ok(await page.locator('.overview-metrics').evaluate(el=>{const hero=document.querySelector('.hero').getBoundingClientRect(),metrics=el.getBoundingClientRect();return metrics.top>=hero.top&&metrics.bottom<=hero.bottom;}),'daily and cost summaries fit inside the vehicle card');
assert.equal(await page.locator('.overview-trend-panel,.overview-activity,main>.status-footer').count(),0);
assert.match(await page.locator('.hero-odometer').innerText(),/累计里程/);
assert.ok(await page.locator('.overview-power .battery-track').evaluate(el=>el.getBoundingClientRect().height>=6));
await page.evaluate(()=>{state.recording.last_sample='合成最新采集';state.recording.status='failed';state.recording.error='合成采集失败';updateHeartbeat();});
assert.match(await page.locator('.overview-collection').innerText(),/合成最新采集/);
assert.match(await page.locator('.overview-collection-state').innerText(),/采集失败/);
assert.equal(await page.locator('.overview-collection-error').innerText(),'合成采集失败');
await page.evaluate(()=>{state.recording.error='';updateHeartbeat();});
assert.equal(await page.locator('.overview-collection-error').isVisible(),false);
await page.locator('#overview-attention [data-attention-target]').last().focus();
await page.evaluate(()=>updateHeartbeat());
assert.ok(await page.evaluate(()=>!!document.activeElement.closest('#overview-attention')),'heartbeat retains focus on inline recovery control');
await page.evaluate(()=>document.activeElement.blur());
await page.locator('[data-overview-tool="settings"]').click();await page.waitForFunction(()=>page==='settings');
assert.equal(await page.locator('#interval').count(),1);
await page.getByRole('button',{name:'← 返回总览原位置',exact:true}).click();
await page.locator('[data-overview-tool="parameters"]').first().click();
await page.locator('#vehicle-search').waitFor();
await page.getByRole('button',{name:'← 返回总览原位置',exact:true}).click();
await page.locator('[data-overview-tool="calendar"]').click();
await page.waitForFunction(()=>page==='calendar');
await page.getByRole('button',{name:'← 返回总览原位置',exact:true}).click();
assert.equal(await page.locator('#overview-record-filter').inputValue(),'charge_end');
await page.evaluate(()=>{window.__overviewOriginal={model:structuredClone(state.model),profile:structuredClone(state.profile),vehicle:state.vehicle};state.model.doors.find(d=>d.name==='左后').door='打开';render();});
await page.locator('[data-overview-status="attention"]').click();
await page.locator('.overview-vehicle-alerts [data-overview-part="lr"]').click();
assert.match(await page.locator('#overview-part-detail').innerText(),/左后门.*打开/s);
await page.evaluate(()=>render());
assert.equal(await page.locator('.overview-part[data-overview-part="lr"]').getAttribute('aria-pressed'),'true','refresh preserves selected part');
await page.locator('.overview-part[data-overview-part="lr"]').focus();
await page.evaluate(()=>{state.model.doors.find(d=>d.name==='左后').door='关闭';render();});
assert.equal(await page.evaluate(()=>document.activeElement?.dataset.overviewPart),'lr','updated door state preserves keyboard focus');
await page.evaluate(()=>{state.vehicle='other-synthetic';state.model.doors.forEach(d=>d.door='关闭');render();});
assert.equal(await page.locator('#overview-part-detail').isVisible(),false,'vehicle identity closes old details');
await page.evaluate(()=>{state.profile.image='';state.model.metric_details={battery:{value:null,unit:'%'},range:{value:null,unit:'km'}};render();});
assert.equal(await page.locator('.overview-power .battery-track').count(),0,'unknown battery never becomes zero');
assert.equal(await page.locator('.overview-vehicle-diagram img').count(),0,'unconfigured vehicle has no official car image');
await page.evaluate(()=>{Object.assign(state,window.__overviewOriginal);render();scrollTo(0,700);});
// Save the actual click position after the approved map/records group swap.
await page.getByRole('button',{name:'去补账',exact:true}).scrollIntoViewIfNeeded();
const scroll=await page.evaluate(()=>scrollY);
await page.getByRole('button',{name:'去补账',exact:true}).click();await page.getByRole('button',{name:'← 返回总览原位置',exact:true}).click();assert.equal(await page.locator('#overview-record-filter').inputValue(),'charge_end');assert.ok(Math.abs(await page.evaluate(()=>scrollY)-scroll)<2);
for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);
 for(const width of [1024,1280,1440,1920]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width} overflow`);
  const columns=await page.locator('.hero').evaluate(el=>{const [identity,power,art]=['.hero-copy','.overview-power','.hero-car'].map(s=>el.querySelector(s).getBoundingClientRect());return identity.right<=power.left+1&&power.right<=art.left+1;});
  assert.ok(columns,`${theme} ${width}: identity, power and image stay separate`);
  const compact=await page.evaluate(()=>{const power=document.querySelector('.overview-power-values'),battery=power.querySelector('.metric-value').getBoundingClientRect(),range=power.querySelector('.overview-range').getBoundingClientRect();const hero=document.querySelector('.hero').getBoundingClientRect(),metrics=document.querySelector('.overview-metrics').getBoundingClientRect();const rows=[...document.querySelectorAll('.overview-metrics>.metric')].map(el=>{const label=el.querySelector('.metric-label').getBoundingClientRect(),value=el.querySelector('.metric-value').getBoundingClientRect();return Math.abs(label.left-value.left)<=1&&value.top>=label.bottom;});return {adjacent:range.left-battery.right<=32,inside:metrics.top>=hero.top&&metrics.bottom<=hero.bottom,rows:rows.every(Boolean),aligned:Math.abs(document.querySelector('#overview-today-value').getBoundingClientRect().top-document.querySelector('#overview-cost-value').getBoundingClientRect().top)<=1};});
  assert.ok(compact.adjacent&&compact.inside&&compact.rows&&compact.aligned,`${theme} ${width}: compact hero summaries ${JSON.stringify(compact)}`);
  const hintInStatus=await page.locator('#overview-attention').evaluate(el=>{
   const hint=el.getBoundingClientRect(),status=document.querySelector('.overview-collection-row').getBoundingClientRect();
   return hint.top>=status.top&&hint.bottom<=status.bottom&&hint.left>=status.left&&hint.right<=status.right+1;
  });
  assert.ok(hintInStatus,`${theme} ${width}: cache hint shares collection status flow`);
  const bounds=await page.evaluate(()=>{const box=s=>document.querySelector(s).getBoundingClientRect();const [map,vehicle]=[...document.querySelector('.overview-health').children].map(e=>e.getBoundingClientRect());const [records,tasks]=[...document.querySelector('.overview-work-grid').children].map(e=>e.getBoundingClientRect());return {collectionAbove:box('.overview-collection').bottom<=map.top,cardTop:Math.abs(map.top-vehicle.top),cardBottom:Math.abs(map.bottom-vehicle.bottom),recordWidth:Math.abs(records.width-tasks.width)};});
  assert.ok(bounds.collectionAbove&&bounds.cardTop<=1&&bounds.cardBottom<=1&&bounds.recordWidth<=1,JSON.stringify(bounds));
 }
}
await page.setViewportSize({width:1440,height:1000});await page.locator('#overview-record-filter').selectOption('all');await page.getByLabel('外观',{exact:true}).selectOption('light');await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:'/tmp/zeekr-overview-production-desktop.png',fullPage:true});
report={...report,context:'other-vehicle'};ledger={...ledger,context:'other-vehicle'};await page.getByRole('button',{name:'重新读取记录汇总',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#overview-today-value').textContent==='未知');assert.equal(await page.locator('#overview-cost-value').innerText(),'未知');assert.match(await page.locator('#overview-records').innerText(),/读取失败/);
assert.deepEqual(f.errors,[]);assert.equal(f.external.length,0);console.log('PASS overview actual-only zero, partial distance, calendar return, door selection/context reset, unknown battery, return/filter/scroll, context rejection, 8 desktop viewport/theme checks');
}catch(error){await f.fail(error);throw error;}finally{await f.close();}})().catch(e=>{console.error(e);process.exit(1)});
