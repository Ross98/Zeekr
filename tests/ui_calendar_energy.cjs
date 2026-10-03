const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture(),{page,origin}=f;
 try{
  const state=await (await page.request.get(origin+'/api/state')).json();
  const saved=await page.request.post(origin+'/api/insights/ledger',{headers:{Origin:origin,'X-Request-Key':state.request_key},data:{action:'save',context:state.insights_context,revision:0,event_id:'report-charge',date:'2026-09-19',source:'home',amount:'30',metered_kwh:'40'}});
  assert.equal(saved.status(),200);
  await page.getByRole('button',{name:'用车日历',exact:true}).click();
  await page.getByLabel('日历月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取用车日历',exact:true}).click();
  await page.locator('.calendar-summary').waitFor();
  await page.locator('[data-calendar-mode="energy"]').click();
  await page.locator('[data-calendar-day="2026-09-20"]').click();
  const api=await (await page.request.get(origin+'/api/insights/calendar?date=2026-09-01')).json();
  const day=api.days.find(d=>d.date==='2026-09-20');
  assert.ok(day.energy_cost.estimated_cents>0);
  assert.ok(day.energy_cost.known_kwh<day.energy_cost.energy_kwh);
  const corner=page.locator('[data-calendar-day="2026-09-20"] .calendar-day-consumption');
  assert.match(await corner.innerText(),/kWh/);
  assert.match(await corner.innerText(),/元/);
  assert.doesNotMatch(await corner.innerText(),/部分/);
  const expected=(day.energy_cost.estimated_cents/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
  assert.ok((await corner.innerText()).includes(expected));
  assert.match(await page.locator('#calendar-day-detail').innerText(),/仅已知价格部分/);
  assert.match(await page.locator('[data-calendar-day="2026-09-20"]').innerText(),/部分可估/);
  await page.reload();await page.locator('.calendar-summary').waitFor();
  assert.equal(await page.locator('#calendar-view').inputValue(),'energy');
  assert.equal(await page.locator('#calendar-selected').inputValue(),'2026-09-20');
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
  console.log('CALENDAR_ENERGY_PASS: partial battery cost, separate payments, URL refresh and no cloud');
 }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
