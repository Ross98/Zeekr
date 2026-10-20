// Retired parking workspace; local trips/calendar and saved-evidence API remain.
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 const requests=[];
 const f=await fixture({initialResearch:false,beforeGoto:async page=>{
  page.on('request',r=>requests.push(new URL(r.url()).pathname));
 }}),{page}=f;
 try{
  await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
  assert.equal(await page.getByRole('button',{name:'停车观测',exact:true}).count(),0,'parking has no independent entry');
  assert.equal(await page.locator('[data-section-task="parking"],[data-insight-view="parking"]').count(),0);
  await page.getByRole('button',{name:'充电曲线对比',exact:true}).click();
  await page.getByLabel('充电 A 月份',{exact:true}).waitFor();
  for(const query of ['?p=energy&t=parking&start=2026-09-19&end=2026-09-20&q=1','?p=insights&t=parking&date=2026-09-19']){
   await page.goto(f.origin+'/'+query);
   await page.getByLabel('轨迹日期',{exact:true}).waitFor();
   assert.equal(await page.getByLabel('轨迹日期',{exact:true}).inputValue(),'2026-09-19');
   assert.equal(await page.locator('#navigation [data-page="tracks"]').getAttribute('aria-current'),'page');
   assert.equal(new URL(page.url()).searchParams.get('s'),'local');
   assert.equal(new URL(page.url()).searchParams.get('t'),null);
   await page.reload();await page.getByLabel('轨迹日期',{exact:true}).waitFor();
   assert.equal(await page.getByLabel('轨迹日期',{exact:true}).inputValue(),'2026-09-19');
  }
  await page.getByRole('button',{name:'用车日历',exact:true}).click();
  await page.getByLabel('日历月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取用车日历',exact:true}).click();
  await page.locator('[data-calendar-day="2026-09-19"]').click();
  await page.getByText('当日采集说明',{exact:true}).click();
  assert.match(await page.locator('#calendar-day-detail').innerText(),/有停车观测/);
  assert.ok(!requests.includes('/parking.js'),'retired workspace script is never loaded');
  assert.ok(!requests.includes('/api/insights/parking'),'normal navigation does not trigger separate parking analysis');
  const data=await page.evaluate(()=>api('/api/insights/parking?start=2026-09-19&end=2026-09-20'));
  assert.ok(Array.isArray(data.events),'saved parking data remains available');
  assert.ok(data.events.length,'synthetic parking evidence still produces events');
  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   for(const width of [1024,1280,1440]){
    await page.setViewportSize({width,height:1000});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.equal(await page.locator('[data-section-task="parking"],[data-insight-view="parking"]').count(),0);
   }
  }
  assert.deepEqual(f.errors,[]);assert.ok(f.posts.every(url=>/^\/api\/analysis\/[^/]+\/cancel$/.test(new URL(url).pathname)),'navigation may only cancel local analysis jobs');
  console.log('UI_PARKING_RETIREMENT_PASS: entry removed; old URLs/reload; calendar evidence; parking API; desktop themes');
 }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
