const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{const f=await fixture({initialResearch:false}),{page}=f;try{
  const job='/api/analysis/'+'a'.repeat(32);let starts=0,polls=0,prefer;
  await page.route('**/api/insights/calendar?*',route=>{starts++;prefer=route.request().headers().prefer;return route.fulfill({status:202,json:{analysis_job_url:job,retry_after_ms:1}});});
  await page.route('**'+job,route=>route.fulfill(++polls===1?{status:202,json:{analysis_job_url:job,retry_after_ms:1}}:{json:{context:'synthetic',result:'complete'}}));
  assert.deepEqual(await page.evaluate(()=>api('/api/insights/calendar?month=2026-10')),{context:'synthetic',result:'complete'});
  assert.equal(prefer,'respond-async');assert.equal(starts,1);assert.equal(polls,2);
  for(const path of ['/api/timeline','/api/place-history','/api/year-review','/api/place-corrections','/api/charging/series','/api/charging/process','/api/charging/statistics']){
    let header;
    await page.route('**'+path+'?test=1',route=>{header=route.request().headers().prefer;return route.fulfill({json:{result:'complete'}});});
    await page.evaluate(path=>api(path+'?test=1'),path);assert.equal(header,'respond-async',path);
  }
  await page.route('**/api/insights/parking?*',route=>route.fulfill({status:202,json:{analysis_job_url:'https://example.invalid/steal',retry_after_ms:1}}));
  assert.match(await page.evaluate(()=>api('/api/insights/parking?date=2026-10-01').catch(e=>e.message)),/任务地址无效/);
  await page.route('**/api/insights/quality?*',route=>route.fulfill({status:429,json:{error:'分析名额已满，请稍后再试。'}}));
  assert.match(await page.evaluate(()=>api('/api/insights/quality?date=2026-10-01').catch(e=>e.message)),/分析名额已满/);
  await page.route('**/api/insights/report?*',async route=>{await page.evaluate(()=>{state.insights_context='changed-account';});return route.fulfill({status:202,json:{analysis_job_url:job,retry_after_ms:1}});});
  assert.match(await page.evaluate(()=>api('/api/insights/report?date=2026-10-01').catch(e=>e.message)),/车辆或账号已切换/);
  assert.equal(polls,2,'old account job is not polled');
  const deadline=await page.evaluate(async()=>{const original=Date.now;let calls=0;Date.now=()=>original()+(calls++?600001:0);try{return await api('/api/timeline?deadline=1').catch(e=>e.message);}finally{Date.now=original;}});
  assert.match(deadline,/超过 10 分钟/);
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);assert.deepEqual(f.posts,[]);
  console.log('ASYNC_ANALYSIS_PASS: Prefer, short polling, same-origin guard, capacity error, account cancellation');
}finally{await f.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
