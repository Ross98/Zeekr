const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{const f=await fixture();const {page}=f;try{
 await page.route('**/api/insights/calendar?*',async route=>{const response=await route.fetch(),data=await response.json();
 [2740,4800,30,0,null,3599.9].forEach((value,i)=>Object.assign(data.days[i],{duration_seconds:value,duration_samples:value===null?0:1,partial_duration_samples:i===1?1:0,ended_trip_count:i===1?2:1,trip_count:i===1?2:1}));
 Object.assign(data.totals,{duration_seconds:44700,duration_samples:5,partial_duration_samples:1,trip_count:6});await route.fulfill({response,json:data});});
 await page.getByRole('button',{name:'用车日历',exact:true}).click();await page.getByLabel('日历月份',{exact:true}).fill('2026-09');await page.getByRole('button',{name:'读取用车日历',exact:true}).click();await page.locator('.calendar-summary').waitFor();
 for(const mode of ['distance','energy','cost','pending']){
 await page.locator('#calendar-view').selectOption(mode);
 for(const [i,want] of ['46 min','1 h 20 min','<1 min','0 min','—','1 h'].entries())assert.equal(await page.locator('.calendar-day').nth(i).locator('.calendar-day-duration').innerText(),want);
 }
 assert.equal(await page.locator('.calendar-duration-total strong').innerText(),'12 h 25 min');
 assert.match(await page.locator('.calendar-duration-total').innerText(),/5 \/ 6/);
 assert.match(await page.locator('.calendar-day-duration').nth(1).getAttribute('title'),/1 \/ 2.*片段/);
 await page.locator('#calendar-view').selectOption('distance');
 await layouts(page,'calendar-duration');
 const overlap=await page.locator('.calendar-day').evaluateAll(days=>days.some(day=>{const d=day.querySelector('.calendar-day-duration');if(!d)return false;const a=d.getBoundingClientRect();return [...day.querySelectorAll('.calendar-flags,.calendar-pending,.calendar-coverage')].some(el=>{const b=el.getBoundingClientRect();return a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;});}));assert.equal(overlap,false,'Duration must not overlap day metadata');
 assert.deepEqual(f.errors,[]);console.log('CALENDAR_DURATION_PASS');
}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
