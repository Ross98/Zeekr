const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture({partialCharge:true}),{page}=f;
  const button=name=>page.getByRole('button',{name,exact:true});
  try{
    await button('能源与充电').click();
    await page.getByLabel('充电记录日期',{exact:true}).fill('2026-09-19');
    await page.locator('.charge-record').first().click();
    await page.locator('#charge-detail').getByText('34.4 kWh（估算）',{exact:true}).waitFor();
    assert.match(await page.locator('#charge-detail').innerText(),/部分记录/);
    assert.match(await page.locator('#charge-detail > div.charge-note').innerText(),/已计入/);
    await layouts(page,'partial-charge-detail');
    await page.getByRole('tab',{name:'统计趋势',exact:true}).click();
    await button('最近 30 天').click();
    await page.locator('.charging-stat-record').waitFor();
    const summary=await page.locator('.charging-stat-summary').innerText();
    assert.match(summary,/34.4/);
    assert.match(summary,/纳入 1.*含片段 1/s);
    assert.match(summary,/观测时段.*1 小时/s);
    assert.match(await page.locator('.charging-daily .energy-caption').innerText(),/片段.*计入/);
    await layouts(page,'partial-charge-statistics');
    const actual=await (await page.request.get(f.origin+'/api/charging/statistics?days=30&mode=all')).json();
    for(const value of [null,0]){
      const unknown={...actual,summary:{...actual.summary,estimated_kwh:value},
        daily:actual.daily.map(day=>({...day,estimated_kwh:value,ac_kwh:null,dc_kwh:null,unknown_kwh:value}))};
      await page.route('**/api/charging/statistics?*',route=>route.fulfill({json:unknown}));
      await button('最近 30 天').click();
      await page.waitForFunction(()=>!chargingAnalyticsBusy);
      const title=await page.locator('.charging-day').last().getAttribute('title');
      assert.match(title,value===null?/未知/:/0 kWh/);
      await page.unroute('**/api/charging/statistics?*');
    }
    assert.deepEqual(f.posts,[]);assert.deepEqual(f.external,[]);assert.deepEqual(f.errors,[]);
    console.log('UI_PARTIAL_CHARGING_PASS: partial detail/statistics, recorded duration, unknown vs zero, themes/mobile/zoom, no writes');
  }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
