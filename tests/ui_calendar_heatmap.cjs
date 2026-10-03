const assert=require('node:assert/strict');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
(async()=>{const f=await fixture();const {page}=f;try{
 await page.route('**/api/insights/calendar?*',async route=>{const response=await route.fetch();const data=await response.json();[0,5,10,10.01,30,30.01,60,60.01,100,100.01,null].forEach((value,i)=>{data.days[i].distance_km=value;});await route.fulfill({response,json:data});});
 await page.getByRole('button',{name:'用车日历',exact:true}).click();
 await page.getByLabel('日历月份',{exact:true}).fill('2026-09');
 await page.getByRole('button',{name:'读取用车日历',exact:true}).click();await page.locator('.calendar-summary').waitFor();
 const days=page.locator('.calendar-day');
 for(let i=0;i<11;i++)assert.equal(await days.nth(i).evaluate(el=>el.style.getPropertyValue('--distance-light')!==''),i!==10);
 assert.notEqual(await days.nth(1).evaluate(el=>getComputedStyle(el).backgroundColor),await days.nth(2).evaluate(el=>getComputedStyle(el).backgroundColor));
 assert.match(await page.locator('.calendar-heatmap-legend').innerText(),/连续渐变/);
 const before=await days.nth(9).evaluate(el=>getComputedStyle(el).backgroundColor);await days.nth(9).click();assert.equal(await days.nth(9).evaluate(el=>getComputedStyle(el).backgroundColor),before);
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);const colors=await days.evaluateAll(elements=>elements.slice(0,10).map(el=>getComputedStyle(el).backgroundColor.match(/[\d.]+/g).slice(0,3).map(Number)));
 const brightness=color=>color.reduce((sum,value,i)=>sum+value*[.2126,.7152,.0722][i],0);
 assert.ok(theme==='dark'?brightness(colors[0])<brightness(colors[9]):brightness(colors[0])>brightness(colors[9]),'More mileage: darker by day, brighter by night');
 await contrast(page,'.calendar-panel');await page.locator('.calendar-panel').screenshot({path:'/tmp/calendar-heatmap-'+theme+'.png'});}
 await page.locator('#calendar-view').selectOption('cost');assert.equal(await page.locator('.calendar-heatmap-legend').count(),0);assert.equal(await page.locator('.calendar-distance').count(),0);
 assert.deepEqual(f.errors,[]);console.log('CALENDAR_HEATMAP_PASS');
}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
