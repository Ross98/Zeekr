const assert=require('node:assert/strict'),fs=require('node:fs');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture(),{page}=f;
 try{
  const snapshot=await page.evaluate(()=>state);
  await page.route('**/api/state',r=>r.fulfill({json:snapshot}));
  await page.evaluate(()=>{
   chargeOwner=state.insights_context;page='energy';chargingTab='statistics';chargingAnalyticsBusy=false;chargingAnalyticsError='';
   chargingStats={summary:{ended_count:3,complete_count:2,partial_count:1,estimated_kwh:83,included_energy_count:3,partial_energy_count:1,excluded_energy_count:0,duration_seconds:3600,included_duration_count:3},records:[],daily:Array.from({length:30},(_,i)=>{const date=new Date(Date.UTC(2026,8,4+i)).toISOString().slice(0,10),kwh=[16,19,23,27].includes(i)?20+i:0;return{date,count:kwh||[5,6].includes(i)?1:0,estimated_kwh:i===6?null:kwh,ac_kwh:i===16?kwh:0,dc_kwh:i!==16?kwh:0,unknown_kwh:0};})};render();
  });
  await page.locator('.charging-daily').waitFor();
  assert.deepEqual(await page.locator('.charging-day-value').allTextContents(),['0','未知','36','39','43','47']);
  fs.mkdirSync('/tmp/zeekr-charging-dates',{recursive:true});
  for(const theme of ['light','dark'])for(const width of [1144,390,320]){
   await page.setViewportSize({width,height:900});
   await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;},theme);
   const result=await page.locator('.charging-daily').evaluate(card=>{
    const cols=[...card.querySelectorAll('.charging-day')];
    return{months:cols.map(c=>c.querySelector('.charging-date-month')?.textContent),days:cols.map(c=>c.querySelector('.charging-date-day')?.textContent),labels:cols.map(c=>c.querySelector('time')?.getBoundingClientRect().top),bottoms:cols.map(c=>c.querySelector('.charging-bar').getBoundingClientRect().bottom),overflow:document.documentElement.scrollWidth>innerWidth};
   });
   assert.equal(result.months[0],'09月');assert.equal(result.months[29],'10月');assert.equal(result.days[0],'04');assert.equal(result.days[29],'03');
   assert.ok(result.labels.every(y=>Math.abs(y-result.labels[0])<1),'date rows aligned');
   assert.ok(result.bottoms.every(y=>Math.abs(y-result.bottoms[0])<1),'bar baselines aligned');assert.equal(result.overflow,false);
   await contrast(page,'.charging-daily');
   await page.locator('.charging-daily').screenshot({path:`/tmp/zeekr-charging-dates/${theme}-${width}.png`});
  }
  await page.locator('.charging-bars').evaluate(el=>{el.scrollLeft=el.scrollWidth;});
  assert.equal(await page.locator('.charging-day time').last().getAttribute('datetime'),'2026-10-03');
  await page.evaluate(()=>{document.documentElement.style.zoom='2';});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'200% zoom stays within page');
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.posts,[]);console.log('UI_CHARGING_DATES_PASS: 30 days, month boundary, aligned bars/dates, light/dark, desktop/mobile, contrast');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exit(1);});
