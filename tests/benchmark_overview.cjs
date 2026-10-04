// Synthetic 5,000-event overview; local APIs only. Run before/after in the same browser.
const {fixture}=require('./ui_insight_helpers.cjs');const fs=require('node:fs');
(async()=>{const f=await fixture({demo:true}),{page}=f;try{
const context=await page.evaluate(()=>state.insights_context),date=await page.evaluate(()=>beijingDate(Date.now()));
const report={context,current:{days:[{date,distance_km:0,trip_count:5000,partial_trip_count:0}],events:Array.from({length:5000},(_,i)=>({id:'synthetic-'+i,kind:i%2?'trip_end':'charge_end',end_time:Date.parse(date+'T12:00:00+08:00')-i*1000,start_soc:70,end_soc:65,distance_km:10,duration_seconds:300,partial:false}))},previous:{days:[],events:[]}};
const ledger={context,totals:{actual_cents:0,actual_count:1},entries:[{actual_cents:0}],events:[]};let reportRequests=0,ledgerRequests=0;
await page.route('**/api/insights/report?*',r=>{reportRequests++;return r.fulfill({json:report})});await page.route('**/api/insights/ledger?*',r=>{ledgerRequests++;return r.fulfill({json:ledger})});
await page.getByRole('button',{name:'总览',exact:true}).first().click();await page.waitForFunction(()=>document.querySelector('#overview-today-value')?.textContent==='0');
const data=await page.evaluate(()=>{
const parent=document.querySelector('#overview-records');const observer=new MutationObserver(()=>{});observer.observe(parent,{childList:true,subtree:true});
const button=document.querySelector('[data-overview-record]');button.focus();const samples=[];
for(let batch=0;batch<5;batch++){const t=performance.now();for(let i=0;i<100;i++)overviewDashboard.mount();samples.push(performance.now()-t);}
const mutations=observer.takeRecords().length;observer.disconnect();return {batches_ms:samples,iterations_per_batch:100,record_dom_mutations:mutations,retains_focus:document.activeElement===button};
});
const baselineReportRequests=reportRequests,baselineLedgerRequests=ledgerRequests;
let release;const delay=new Promise(r=>release=r);await page.route('**/api/insights/report?*',async r=>{reportRequests++;await delay;return r.fulfill({json:report})});await page.route('**/api/insights/ledger?*',async r=>{ledgerRequests++;await delay;return r.fulfill({json:ledger})});
await page.evaluate(()=>{const button=document.querySelector('[data-overview-reload]');for(let i=0;i<10;i++)button.click()});
await page.waitForTimeout(100);release();await page.waitForTimeout(100);
data.repeated_clicks=10;data.report_requests=reportRequests-baselineReportRequests;data.ledger_requests=ledgerRequests-baselineLedgerRequests;data.events=5000;data.browser=await f.browser.version();
if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify(data,null,2));console.log(JSON.stringify(data));
}finally{await f.close()}})().catch(e=>{console.error(e);process.exitCode=1});
