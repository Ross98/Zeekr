const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture(),{page}=f;
 try{
  await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();
  await page.getByRole('button',{name:'常走路线对比',exact:true}).click({timeout:1500});
  await page.getByLabel('路线月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取路线',exact:true}).click();
  await page.getByText(/本月尚无两端都有可信定位的行程/).waitFor();
  await page.route('**/api/insights/routes?*',async route=>{
   const response=await route.fetch(),data=await response.json();
   data.trip_count=2;data.unknown_route_count=0;
   const stats={samples:1,mean:20,median:20,minimum:20,maximum:20};
   data.routes=[{start_place:'place_1',end_place:'place_2',start_label:'家',end_label:'公司',count:2,complete_count:1,partial_count:1,
    distance_km:stats,duration_seconds:{...stats,samples:2,mean:1200,median:1200},estimated_kwh:{...stats,mean:4.3,median:4.3},
    events:[{id:'one',end_time:1790000000000,partial:false,duration_seconds:1200,distance_km:20,estimated_kwh:4.3},{id:'two',end_time:1790000001000,partial:true,duration_seconds:1200,distance_km:null,estimated_kwh:null}]}];
   await route.fulfill({json:data});
  });
  await page.getByRole('button',{name:'读取路线',exact:true}).click();
  await page.locator('#route-comparison').waitFor();
  assert.match(await page.locator('#route-comparison').innerText(),/家 → 公司/);
  assert.match(await page.locator('#route-comparison').innerText(),/1 \/ 2 条有效样本/);
  assert.match(await page.locator('#route-comparison').innerText(),/观测片段.*未知 km.*未知 kWh/s);
  await layouts(page,'route-comparison');
  assert.match(page.url(),/p=tracks/);assert.match(page.url(),/t=routes/);assert.match(page.url(),/month=2026-09/);
  await page.reload();await page.getByLabel('路线月份',{exact:true}).waitFor();
  await page.locator('#route-comparison').waitFor();
  assert.equal(await page.getByLabel('路线月份',{exact:true}).inputValue(),'2026-09');
  await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
  await page.getByLabel('充电记录查询方式',{exact:true}).selectOption('range');
  await page.locator('#charge-date').fill('2026-09-01');await page.locator('#charge-end-date').fill('2026-09-30');
  await page.locator('#charge-end-date').blur();
  await page.waitForURL(/range=range.*end=2026-09-30/);
  await page.reload();await page.locator('#charge-query-mode').waitFor();
  await page.locator('#charge-end-date').waitFor();
  assert.equal(await page.locator('#charge-date').inputValue(),'2026-09-01');
  assert.equal(await page.locator('#charge-end-date').inputValue(),'2026-09-30');
  await page.getByRole('button',{name:'充电账本',exact:true}).click();
  await page.getByLabel('账本月份',{exact:true}).fill('2026-09');
  await page.getByLabel('账本月份',{exact:true}).blur();
  await page.getByRole('button',{name:'读取账本',exact:true}).click();
  await page.locator('#ledger-range').waitFor();
  await page.reload();await page.getByLabel('账本月份',{exact:true}).waitFor();
  await page.locator('#ledger-range').waitFor();
  assert.equal(await page.getByLabel('账本月份',{exact:true}).inputValue(),'2026-09');
  await page.getByRole('button',{name:'总览',exact:true}).first().click();
  await page.goBack();await page.getByLabel('账本月份',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('账本月份',{exact:true}).inputValue(),'2026-09');
  await page.goForward();await page.locator('.hero').waitFor();
  await page.getByRole('button',{name:'用车研究',exact:true}).click();
  await page.getByRole('button',{name:'轻量用车回顾',exact:true}).click();
  await page.getByLabel('回顾日期',{exact:true}).fill('2026-09-20');
  await page.getByRole('button',{name:'查看这一周',exact:true}).click();
  await page.locator('#usage-review').waitFor();
  assert.match(await page.locator('#usage-review').innerText(),/1 次充电未关联账单/);
  assert.match(await page.locator('#usage-review .review-cost').innerText(),/未知/);
  await layouts(page,'usage-review');
  await page.getByRole('button',{name:'去充电账本',exact:true}).click();
  assert.equal(await page.getByLabel('账本月份',{exact:true}).inputValue(),'2026-09');
  await page.getByRole('button',{name:'设置',exact:true}).first().click();
  assert.match(await page.locator('#release-summary').innerText(),/尚未记录发布清单/);
  await page.evaluate(()=>{state.release={status:'recorded',base_version:'a'.repeat(40),features:[{label:'合成上线功能',status:'matched'},{label:'合成不一致功能',status:'mismatch'}]};render();});
  assert.match(await page.locator('#release-summary').innerText(),/aaaaaaaaaaaa.*已上线（文件一致）.*文件与发布清单不一致/s);
  const url=page.url();assert.doesNotMatch(url,/latitude|longitude|name=|token|context|SECRET/);
  assert.deepEqual(f.posts,[]);assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
  console.log('UI_REMAINING_DASHBOARD_PASS');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
