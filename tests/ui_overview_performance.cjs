const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture({demo:true}),{page}=f;
 try{
  const context=await page.evaluate(()=>state.insights_context),date=await page.evaluate(()=>beijingDate(Date.now()));
  const report=(owner,distance,day=date)=>({context:owner,current:{days:[{date:day,distance_km:distance,trip_count:1,partial_trip_count:0}],events:[{id:'synthetic-trip',kind:'trip_end',end_time:Date.parse(day+'T12:00:00+08:00'),start_soc:70,end_soc:65,distance_km:distance,duration_seconds:300,partial:false}]},previous:{days:[],events:[]}});
  const ledger=owner=>({context:owner,totals:{actual_cents:0,actual_count:1},entries:[{actual_cents:0},{actual_cents:null}],events:[]});
  await page.route('**/api/insights/report?*',r=>r.fulfill({json:report(context,0)}));
  await page.route('**/api/insights/ledger?*',r=>r.fulfill({json:ledger(context)}));
  await page.getByRole('button',{name:'总览',exact:true}).first().click();
  await page.waitForFunction(()=>document.querySelector('#overview-today-value')?.textContent==='0');
  const stable=await page.evaluate(()=>{
   const button=document.querySelector('[data-overview-record]');button.focus();
   const targets=['overview-records','overview-tasks','overview-trend'];
   const observers=targets.map(id=>{const o=new MutationObserver(()=>{});o.observe(document.getElementById(id),{childList:true,subtree:true});return o});
   for(let i=0;i<20;i++)overviewDashboard.mount();
   const mutations=observers.reduce((n,o)=>{const count=o.takeRecords().length;o.disconnect();return n+count},0);
   return {mutations,focused:document.activeElement===button};
  });
  assert.equal(stable.mutations,0,'unchanged mounts preserve records, task controls and trend nodes');
  assert.equal(stable.focused,true,'unchanged mounts retain keyboard focus');
  assert.equal(await page.locator('#overview-cost-value').innerText(),'0');
  assert.match(await page.locator('#overview-cost-note').innerText(),/1 项待补/);

  const pending={report:[],ledger:[]};
  for(const kind of ['report','ledger'])await page.route(`**/api/insights/${kind}?*`,route=>new Promise(resolve=>pending[kind].push({route,resolve})));
  const waitRequests=async count=>{const until=Date.now()+5000;while(pending.report.length<count||pending.ledger.length<count){assert.ok(Date.now()<until,'overview requests arrived');await new Promise(r=>setTimeout(r,10))}};
  const release=async(index,owner,distance,day=date)=>{
   await Promise.all(['report','ledger'].map(async kind=>{const job=pending[kind][index];await job.route.fulfill({json:kind==='report'?report(owner,distance,day):ledger(owner)});job.resolve()}));
  };
  await page.evaluate(()=>{const button=document.querySelector('[data-overview-reload]');for(let i=0;i<10;i++)button.click()});
  await waitRequests(1);await page.evaluate(()=>new Promise(requestAnimationFrame));
  assert.equal(pending.report.length,1,'ten reload clicks share one report request');
  assert.equal(pending.ledger.length,1,'ten reload clicks share one ledger request');
  await page.evaluate(()=>{state.trip_records_revision++;overviewDashboard.mount()});
  await page.waitForFunction(()=>document.querySelector('#overview-today-value').textContent==='未知');
  await waitRequests(2);
  await release(1,context,23);await page.waitForFunction(()=>document.querySelector('#overview-today-value').textContent==='23');
  await release(0,context,0);assert.equal(await page.locator('#overview-today-value').innerText(),'23','older revision cannot replace accepted results');

  await page.evaluate(()=>{state.insights_context='synthetic-other-owner';overviewDashboard.mount()});
  await waitRequests(3);
  assert.equal(await page.locator('#overview-cost-value').innerText(),'未知','account switch clears old bills before response');
  await release(2,context,99);
  await page.getByText('行程汇总读取失败，请重试；费用汇总读取失败，请重试',{exact:true}).waitFor();
  assert.equal(await page.locator('#overview-today-value').innerText(),'未知','mismatched account response stays unknown');
  await page.getByRole('button',{name:'重新读取记录汇总',exact:true}).click();
  await waitRequests(4);
  await release(3,'synthetic-other-owner',0);await page.waitForFunction(()=>document.querySelector('#overview-today-value').textContent==='0');
  assert.equal(await page.locator('#overview-cost-value').innerText(),'0');
  await page.getByRole('button',{name:'30 天',exact:true}).click();
  assert.equal(await page.locator('.overview-day').count(),30,'range change invalidates summary');
  await page.evaluate(()=>{state.charge_records_revision++;overviewDashboard.mount()});
  await waitRequests(5);await release(4,'synthetic-other-owner',7);
  await page.waitForFunction(()=>document.querySelector('#overview-today-value').textContent==='7');
  const tomorrow=await page.evaluate(()=>{
   const OriginalDate=Date,offset=86400000;
   window.Date=class extends OriginalDate{constructor(...args){super(...(args.length?args:[OriginalDate.now()+offset]))}static now(){return OriginalDate.now()+offset}};
   overviewDashboard.mount();return beijingDate(Date.now());
  });
  await waitRequests(6);
  assert.equal(new URL(pending.report[5].route.request().url()).searchParams.get('date'),tomorrow,'Beijing day rollover requests new date');
  await release(5,'synthetic-other-owner',8,tomorrow);
  await page.waitForFunction(()=>document.querySelector('#overview-today-value').textContent==='8');
  assert.deepEqual(f.errors,[]);
  console.log('UI_OVERVIEW_PERFORMANCE_PASS: stable DOM/focus, request coalescing, revision/account isolation, unknown/zero, retry, range and day rollover');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
