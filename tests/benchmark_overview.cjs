// Synthetic 5,000-event overview; local APIs only. Run before/after in the same browser.
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
const fs=require('node:fs'),path=require('node:path');
(async()=>{
  let report,costs,reportRequests=0,costRequests=0,release;
  const f=await fixture({demo:true,initialResearch:false,beforeGoto:async page=>{
    // Mock the first overview read too: no real startup job can populate its cache.
    await page.route('**/api/insights/report?*',async route=>{
      reportRequests++;
      const {context,date}=await page.evaluate(()=>({context:state.insights_context,date:beijingDate(Date.now())}));
      report={context,current:{days:[{date,distance_km:0,trip_count:2500,partial_trip_count:0}],
        events:Array.from({length:5000},(_,i)=>({id:'synthetic-'+i,kind:i%2?'trip_end':'charge_end',
          end_time:Date.parse(date+'T12:00:00+08:00')-i*1000,start_soc:70,end_soc:65,
          distance_km:10,duration_seconds:300,partial:false}))},previous:{days:[],events:[]}};
      await route.fulfill({json:report});
    });
    await page.route('**/api/insights/costs?*',async route=>{
      costRequests++;
      const context=await page.evaluate(()=>state.insights_context);
      costs={context,totals:{actual_cents:0,actual_charge_count:1,life_count:0,
        unknown_charge_count:0,unlinked_charge_count:0}};
      await route.fulfill({json:costs});
    });
  }}),{page}=f;
  try{
    const ready=()=>page.waitForFunction(()=>
      document.querySelector('#overview-today-value')?.textContent==='0'&&
      document.querySelector('#overview-cost-value')?.textContent==='0'&&
      document.querySelector('[data-overview-record="synthetic-0"]')&&
      !document.querySelector('#overview-records')?.textContent.includes('正在读取已保存记录'));
    await ready();
    assert.equal(await page.locator('#overview-today-note').innerText(),'2500 次行程');
    assert.equal(reportRequests,1,'one mocked initialization report');
    assert.equal(costRequests,1,'one mocked initialization cost summary');
    const data=await page.evaluate(()=>{
      const parent=document.querySelector('#overview-records');
      const observer=new MutationObserver(()=>{});observer.observe(parent,{childList:true,subtree:true});
      const button=document.querySelector('[data-overview-record]');button.focus();const samples=[];
      for(let batch=0;batch<5;batch++){
        const t=performance.now();for(let i=0;i<100;i++)overviewDashboard.mount();
        samples.push(performance.now()-t);
      }
      const mutations=observer.takeRecords().length;observer.disconnect();
      return {batches_ms:samples,iterations_per_batch:100,record_dom_mutations:mutations,
        retains_focus:document.activeElement===button};
    });
    assert.equal(data.record_dom_mutations,0,'unchanged mounts do not replace record DOM');
    assert.equal(data.retains_focus,true,'unchanged mounts retain focus');
    assert.equal(data.batches_ms.length,5);
    assert.ok(data.batches_ms.every(ms=>Number.isFinite(ms)&&ms>=0));
    const baselineReportRequests=reportRequests,baselineCostRequests=costRequests;
    let reportStarted,costStarted;
    const reports=new Promise(resolve=>reportStarted=resolve),expenses=new Promise(resolve=>costStarted=resolve);
    const gate=new Promise(resolve=>release=resolve);
    await page.route('**/api/insights/report?*',async route=>{
      reportRequests++;reportStarted();await gate;await route.fulfill({json:report});
    });
    await page.route('**/api/insights/costs?*',async route=>{
      costRequests++;costStarted();await gate;await route.fulfill({json:costs});
    });
    let timer;
    try{
      const started=Promise.race([Promise.all([reports,expenses]),
        new Promise((_,reject)=>timer=setTimeout(()=>reject(Error('Benchmark reload requests did not arrive')),10000))]);
      await page.evaluate(()=>{const button=document.querySelector('[data-overview-reload]');for(let i=0;i<10;i++)button.click()});
      await started;
    }finally{clearTimeout(timer);}
    assert.equal(reportRequests-baselineReportRequests,1,'ten clicks share one report request');
    assert.equal(costRequests-baselineCostRequests,1,'ten clicks share one cost-summary request');
    release();await ready();
    data.repeated_clicks=10;data.report_requests=reportRequests-baselineReportRequests;
    data.cost_requests=costRequests-baselineCostRequests;data.events=report.current.events.length;
    data.browser=await f.browser.version();
    assert.equal(data.report_requests,1);assert.equal(data.cost_requests,1);
    assert.equal(data.events,5000);
    assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);assert.deepEqual(f.posts,[]);
    const json=JSON.stringify(data,null,2);
    if(process.argv[2]){
      const output=path.resolve(process.argv[2]);fs.mkdirSync(path.dirname(output),{recursive:true});
      fs.writeFileSync(output,json);
    }
    console.log(json);
  }finally{if(release)release();await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
