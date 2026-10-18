const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 let initialReport,initialReports=0;
 const f=await fixture({initialResearch:false,beforeGoto:async page=>{
   // Install before navigation: the overview's real asynchronous report must not
   // overlap the account-switch cancellation scenario under test.
   initialReport=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/insights/report'&&response.status()===200);
   await page.route('**/api/insights/report?*',async route=>{
     initialReports++;
     const context=await page.evaluate(()=>state.insights_context);
     return route.fulfill({json:{context,current:{days:[],events:[]},previous:{days:[],events:[]}}});
   });
 }}),{page}=f;try{
  await (await initialReport).finished();assert.equal(initialReports,1);
  await page.waitForFunction(()=>Boolean(state?.insights_context));
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
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);assert.deepEqual(f.posts,[f.origin+job+'/cancel']);
  await page.evaluate(()=>{state.insights_context='synthetic';});
  let cancellations=0;
  const cancelJob='/api/analysis/'+'b'.repeat(32);
  await page.route('**/api/insights/calendar?cancel=1',route=>route.fulfill({status:202,json:{analysis_job_url:cancelJob,retry_after_ms:50}}));
  await page.route('**'+cancelJob,route=>route.fulfill({status:202,json:{analysis_job_url:cancelJob,retry_after_ms:50}}));
  await page.route('**'+cancelJob+'/cancel',route=>{cancellations++;assert.equal(route.request().method(),'POST');return route.fulfill({json:{cancelled:true}});});
  const cancelled=await page.evaluate(async()=>{
    const controller=new AbortController();
    const pending=api('/api/insights/calendar?cancel=1',undefined,50000,{signal:controller.signal}).catch(e=>e.message);
    setTimeout(()=>controller.abort(),150);
    return Promise.race([pending,new Promise(resolve=>setTimeout(()=>resolve("cancellation ignored"),1500))]);
  });
  assert.match(cancelled,/取消/);
  assert.equal(cancellations,1);
  assert.deepEqual(f.posts,[f.origin+job+'/cancel',f.origin+cancelJob+'/cancel']);
  const timeoutJob='/api/analysis/'+'e'.repeat(32);let timeoutCancels=0;
  await page.route('**/api/insights/calendar?timeout=1',route=>route.fulfill({status:202,json:{analysis_job_url:timeoutJob,retry_after_ms:50}}));
  await page.route('**'+timeoutJob,async route=>{await new Promise(resolve=>setTimeout(resolve,400));try{await route.fulfill({status:202,json:{analysis_job_url:timeoutJob,retry_after_ms:50}});}catch{}});
  await page.route('**'+timeoutJob+'/cancel',route=>{timeoutCancels++;return route.fulfill({json:{cancelled:true}});});
  assert.match(await page.evaluate(()=>api('/api/insights/calendar?timeout=1',undefined,150).catch(e=>e.message)),/超时/);
  assert.equal(timeoutCancels,1,'poll timeout cancels backend subscription');
  assert.deepEqual(f.posts,[f.origin+job+'/cancel',f.origin+cancelJob+'/cancel',f.origin+timeoutJob+'/cancel']);
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
  console.log('ASYNC_ANALYSIS_PASS: Prefer, short polling, same-origin guard, capacity error, account cancellation');
}finally{await f.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
