const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture({demo:true,partialCharge:true,automatic:true}),{page}=f;
 try{
  await page.setViewportSize({width:390,height:844});
  await page.locator('#navigation [data-page="overview"]').evaluate(el=>el.click());
  assert.ok(await page.locator('.overview-metrics').evaluate(el=>el.getBoundingClientRect().bottom)<844,'battery and range fit first mobile viewport');
  await page.locator('#overview-attention').getByRole('button',{name:'查看处理',exact:true}).click();
  await page.locator('#quality-workspace').waitFor();
  assert.equal(await page.locator('#sampling-help').count(),0,'diagnostics replaces settings parent content');
  await page.locator('#navigation [data-page="energy"]').evaluate(el=>el.click());
  await page.getByRole('button',{name:'充电账本',exact:true}).click();
  await page.locator('#ledger-month').waitFor();
  assert.equal(await page.locator('.energy-top').count(),0,'ledger replaces energy parent content');
  assert.equal(await page.locator('.energy-details').count(),0);
  assert.ok(await page.locator('#ledger-month').evaluate(el=>el.getBoundingClientRect().top)<844,'ledger controls near first viewport');
  await page.getByLabel('账本月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取账本',exact:true}).click();
  await page.getByText('已录账单中费用未知',{exact:true}).waitFor();
  assert.match(await page.locator('#ledger-range').innerText(),/未关联充电记录/);
  await page.evaluate(()=>render());
  assert.equal(await page.locator('.energy-top').count(),0,'background render preserves task');
  await page.getByRole('button',{name:'充电状态',exact:true}).click();
  await page.locator('.energy-top').waitFor();
  await page.getByRole('button',{name:'充电记录',exact:true}).click();
  assert.equal(await page.locator('.energy-top').count(),0);
  await page.locator('#charge-history').waitFor();
  await page.locator('#navigation [data-page="settings"]').evaluate(el=>el.click());
  assert.match(await page.locator('#collection-status').innerText(),/采集配置.*后台进程.*最近成功观测/s);
  await page.locator('#navigation [data-page="insights"]').evaluate(el=>el.click());
  await page.route('**/api/insights/research?*',async route=>{
   const response=await route.fetch(),data=await response.json();
   data.counts.reads=0;data.counts.samples=0;
   await route.fulfill({json:data});
  });
  await page.getByRole('button',{name:'分析本地数据',exact:true}).click();
  await page.getByRole('heading',{name:'本期暂无归档',exact:true}).waitFor();
  assert.equal(await page.locator('.research-catalog').getAttribute('open'),null);
  assert.equal(await page.locator('.research-field-table').isVisible(),false);
  await page.getByRole('button',{name:'扩大到近 30 天',exact:true}).click();
  assert.match(await page.locator('#research-range-draft').innerText(),/点击分析/);
  await page.locator('#navigation [data-page="overview"]').evaluate(el=>el.click());
  const targets=await page.locator('.text-link,.closure-summary,.data-explanation>summary').evaluateAll(els=>els.filter(el=>el.checkVisibility()).map(el=>({text:el.textContent,height:el.getBoundingClientRect().height})));
  assert.ok(targets.every(el=>el.height>=44),JSON.stringify(targets));
  for(const theme of ['light','dark'])for(const width of [1440,390,320]){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   await page.setViewportSize({width,height:844});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  }
  assert.deepEqual(f.errors,[]);
  console.log('UI_TASK_LAYOUT_PASS');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
