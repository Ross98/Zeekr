// Concurrent same-origin asset bursts, synthetic service only.
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture();
  try{
    const failed=[],errors=[];
    for(let round=0;round<3;round++){
      const pages=await Promise.all(Array.from({length:6},()=>f.browser.newPage()));
      try{
        for(const page of pages){
          page.on('requestfailed',r=>failed.push({path:new URL(r.url()).pathname,error:r.failure()?.errorText}));
          page.on('pageerror',e=>errors.push(e.message));
        }
        await Promise.all(pages.map(async page=>{
          await page.goto(f.origin);await page.getByRole('button',{name:'用车研究',exact:true}).click();
          await page.getByRole('button',{name:'充电曲线对比',exact:true}).waitFor();
        }));
      }finally{await Promise.all(pages.map(page=>page.close()));}
    }
    assert.deepEqual(failed,[]);assert.deepEqual(errors,[]);
    console.log('UI_INSIGHTS_STARTUP_PASS: 18 cold page loads in six-page concurrent bursts, all scripts/nav ready, no failed requests or script errors');
  }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
