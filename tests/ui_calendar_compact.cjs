const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture(),{page}=f;
 try{
  await page.getByRole('button',{name:'用车日历',exact:true}).click();
  await page.getByLabel('日历月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取用车日历',exact:true}).click();
  await page.locator('.calendar-summary').waitFor();
  await page.locator('[data-calendar-day="2026-09-19"]').click();
  assert.equal(await page.locator('.calendar-day-overview>div').count(),4);
  const day=page.locator('#calendar-day-detail');
  assert.match(await day.innerText(),/待补账 1 次/);
  assert.doesNotMatch(await page.locator('.calendar-events').innerText(),/起止 SOC|电池参考成本|充电损耗/);
  const trip=page.locator('[data-calendar-event="report-trip-night"]');
  await trip.click();
  assert.equal(await trip.getAttribute('aria-expanded'),'true');
  assert.equal(await page.locator('.calendar-event-trip #calendar-event-detail').count(),1);
  assert.match(await page.locator('#calendar-event-detail').innerText(),/起止 SOC|SOC 电量估算/);
  const bounds=await page.evaluate(()=>{
   const left=document.querySelector('.calendar-panel').getBoundingClientRect(),right=document.querySelector('.calendar-detail-column');
   right.scrollTop=100;
   return {difference:Math.abs(left.height-right.getBoundingClientRect().height),scroll:right.scrollTop};
  });
  assert.ok(bounds.difference<1,'Expanded detail keeps the month height');
  assert.ok(bounds.scroll>0,'Long details scroll inside the right card');
  await page.evaluate(()=>render());
  assert.equal(await trip.getAttribute('aria-expanded'),'true');
  await trip.click();
  assert.equal(await trip.getAttribute('aria-expanded'),'false');
  assert.equal(await page.locator('#calendar-event-detail').count(),0);
  await page.locator('[data-calendar-bill="report-charge"]').click();
  await page.locator('#calendar-bill-amount').fill('0');
  await page.evaluate(()=>render());
  assert.equal(await page.locator('#calendar-bill-amount').inputValue(),'0');
  await page.locator('[data-calendar-day="2026-09-21"]').click();
  assert.match(await day.innerText(),/未来日期/);
  assert.equal(await page.locator('.calendar-day-overview dd').first().innerText(),'—');
  await page.locator('[data-calendar-day="2026-09-01"]').click();
  assert.equal(await page.locator('.calendar-day-overview dd').first().innerText(),'未知');
  await page.locator('[data-calendar-day="2026-09-19"]').click();
  await layouts(page,'calendar-compact');
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);assert.deepEqual(f.posts,[]);
  console.log('CALENDAR_COMPACT_PASS: summary, warnings, inline toggle, render preservation, bill draft, unknown/future and desktop themes');
 }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
