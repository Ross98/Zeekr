const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{const f=await fixture({initialResearch:false}),{page}=f;try{
  await page.waitForFunction(()=>Boolean(state?.insights_context));
  let starts=0,cancels=0;
  await page.route('**/api/insights/calendar?*',route=>{starts++;return route.fulfill({status:202,json:{analysis_job_url:'/api/analysis/'+'c'.repeat(32),retry_after_ms:50}});});
  await page.route('**/api/insights/report?*',route=>{starts++;return route.fulfill({status:202,json:{analysis_job_url:'/api/analysis/'+'d'.repeat(32),retry_after_ms:50}});});
  await page.route(/\/api\/analysis\/[cd]{32}$/,route=>route.fulfill({status:202,json:{analysis_job_url:new URL(route.request().url()).pathname,retry_after_ms:50}}));
  await page.route(/\/api\/analysis\/[cd]{32}\/cancel$/,route=>{cancels++;return route.fulfill({json:{cancelled:true}});});
  for(const [section,selector] of [['用车日历','[data-calendar="load"]'],['用车周报','[data-report="load"]']]){
    const initialCancels=cancels;
    await page.getByRole('button',{name:section,exact:true}).first().click();
    const load=page.locator(selector);await load.click();
    await page.waitForFunction(()=>document.body.innerText.includes('停止分析'),{},{timeout:2000});
    await page.waitForTimeout(100);const before=starts;await load.click();
    await page.waitForTimeout(150);assert.equal(starts,before,'repeat click keeps one request');
    await page.getByRole('button',{name:'停止分析',exact:true}).click();
    await page.waitForFunction(()=>!document.body.innerText.includes('停止分析'));
    await page.waitForTimeout(200);assert.equal(cancels,initialCancels+1);
    await load.click();await page.waitForFunction(()=>document.body.innerText.includes('停止分析'));
    await page.waitForTimeout(100);
    if(section==='用车日历')await page.locator('#calendar-month').fill('2026-08');
    else await page.locator('#report-period').selectOption('month');
    await page.locator('#page-heading').click();
    await page.waitForTimeout(350);assert.equal(cancels,initialCancels+2);
    assert.equal(await page.getByRole('button',{name:'停止分析',exact:true}).count(),0);
    // Leaving a page also cancels its active subscription.
    await load.click();await page.waitForFunction(()=>document.body.innerText.includes('停止分析'));
    await page.waitForTimeout(100);
    await page.getByRole('button',{name:'车辆',exact:true}).first().click();
    await page.waitForTimeout(350);assert.equal(cancels,initialCancels+3);

  }
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
  console.log('ANALYSIS_CANCEL_PASS: desktop duplicate click, explicit stop, navigation cancellation');
}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
