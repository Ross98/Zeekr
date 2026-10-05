// Desktop parking entry and advancing-time observation display; synthetic inputs only.
const {fixture}=require('./ui_insight_helpers.cjs');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{const f=await fixture(),{page}=f;try{
 const context=await page.evaluate(()=>state.insights_context);
 let requests=0,release;
 const data={context,start_date:'2026-09-19',end_date:'2026-09-20',calculation_version:2,
  comparable_count:1,uncertain_count:0,orphan_count:0,orphan_sessions:[],events:[{
   id:'synthetic-continuous',category:'same_day',start_time:1789772400000,end_time:1789776000000,
   start_trip_id:'a',end_trip_id:'b',duration_seconds:3600,start_soc:70,end_soc:70,
   soc_drop:0,estimated_kwh:0,status:'comparable',parking_status:'parked',open:false,reason_labels:[],sample_count:13,gap_count:0,p_gear_samples:13
  }]};
 await page.route('**/api/insights/parking?*',async route=>{requests++;if(requests===2)await new Promise(resolve=>release=resolve);await route.fulfill({json:data})});
 await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
 await page.getByRole('button',{name:'停车观测',exact:true}).click();
 assert.equal(requests,0,'entry does not analyze automatically');
 await page.locator('#parking-start').fill('2026-09-19');await page.locator('#parking-end').fill('2026-09-20');
 assert.equal(requests,0,'date edits do not analyze automatically');
 await page.getByRole('button',{name:'分析停车观测',exact:true}).click();
 await page.locator('[data-parking-session]').waitFor();
 assert.match(await page.locator('[data-parking-session]').innerText(),/1 小时/);
 assert.match(await page.locator('[data-parking-session]').innerText(),/70% → 70%/);
 await page.getByRole('button',{name:'查看停车详情',exact:true}).click();
 assert.match(await page.locator('#parking-detail').innerText(),/13 条/);
 assert.match(await page.locator('#parking-detail').innerText(),/0 处/);
 assert.match(await page.locator('#parking-detail').innerText(),/P 档辅助证据/);
 assert.match(await page.locator('#parking-detail').innerText(),/13 条有效观测/);
 data.events[0].status='uncertain';data.events[0].soc_drop=null;data.events[0].estimated_kwh=null;data.events[0].reason_labels=['停车期间有异常时间或无效观测'];data.comparable_count=0;data.uncertain_count=1;
 await page.getByRole('button',{name:'分析停车观测',exact:true}).click();
 await page.getByRole('button',{name:'正在分析…',exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'正在分析…',exact:true}).isDisabled(),true);
 while(!release)await new Promise(resolve=>setTimeout(resolve,10));release();
 await page.getByRole('button',{name:'分析停车观测',exact:true}).waitFor();
 assert.match(await page.locator('[data-parking-session]').innerText(),/停车时长/);
 assert.match(await page.locator('[data-parking-session]').innerText(),/耗电暂不计算/);
 assert.doesNotMatch(await page.locator('[data-parking-session]').innerText(),/停车待确认/);
 fs.mkdirSync('/tmp/zeekr-parking-observations-qa',{recursive:true});
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);for(const width of [1440,1280,1024]){
  await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width}`);
  if(width===1440){await page.evaluate(()=>{scrollTo(0,0);document.querySelector('#toast').hidden=true});await page.screenshot({path:`/tmp/zeekr-parking-observations-qa/${theme}.png`,fullPage:true})}
 }}
 assert.deepEqual(f.errors,[]);console.log('DESKTOP_PARKING_OBSERVATIONS_PASS: manual entry, same-value hour, 13 samples, no gap, loading guard, 6 layouts');
}finally{await f.close()}})().catch(e=>{console.error(e);process.exitCode=1});
