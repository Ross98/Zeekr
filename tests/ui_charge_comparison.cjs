const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture(),{page}=f;
  try{
    await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
    await page.getByRole('button',{name:'充电曲线对比',exact:true}).click();
    for(const side of ['A','B']){
      await page.getByLabel(`充电 ${side} 月份`,{exact:true}).fill('2026-07');
      await page.getByRole('button',{name:`读取充电 ${side}`,exact:true}).click();
    }
    await page.getByLabel('充电记录 A',{exact:true}).selectOption('curve-a');
    await page.getByLabel('充电记录 B',{exact:true}).selectOption('curve-b');
    await page.getByRole('button',{name:'比较这两次充电',exact:true}).click();
    await page.getByText('共同观测 SOC：30% — 80%',{exact:true}).waitFor();
    assert.equal(await page.locator('[data-charge-chart]').count(),3);
    assert.ok(await page.locator('[data-charge-chart="power_kw"] .compare-line-a').count()>0);
    assert.match(await page.locator('#charge-compare-summary').innerText(),/直流/);
    assert.match(await page.locator('#charge-compare-summary').innerText(),/交流/);
    assert.match(await page.locator('#charge-compare-summary').innerText(),/10.*12/);
    await page.getByLabel('对比温度',{exact:true}).selectOption('inside_temp');
    await page.getByLabel('查看观测点 A',{exact:true}).selectOption('2');
    await page.evaluate(()=>render());
    assert.equal(await page.getByLabel('对比温度',{exact:true}).inputValue(),'inside_temp');
    assert.equal(await page.getByLabel('查看观测点 A',{exact:true}).inputValue(),'2');
    assert.match(await page.locator('#charge-point-a').innerText(),/40%/);
    await layouts(page,'charge-comparison');
    await page.setViewportSize({width:390,height:1000});
    await page.locator('#charge-comparison-charts').screenshot({path:'/tmp/zeekr-insights-qa/charge-comparison-curves-dark-390.png'});
    await page.getByLabel('充电记录 B',{exact:true}).selectOption('curve-gap');
    await page.getByRole('button',{name:'比较这两次充电',exact:true}).click();
    await page.getByText('存在缺口或 SOC 倒退，区间耗时不比较',{exact:true}).waitFor();
    assert.ok(await page.locator('[data-charge-chart="power_kw"] .compare-line-b').count()>=2);
    await page.route('**/api/insights/charge-comparison?a=*',route=>route.fulfill({status:500,json:{error:'合成比较失败'}}));
    await page.getByRole('button',{name:'比较这两次充电',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'合成比较失败'}).waitFor();
    assert.equal(await page.locator('[data-charge-chart]').count(),3);
    assert.deepEqual(f.posts,[]);assert.deepEqual(f.external,[]);assert.deepEqual(f.errors,[]);
    await page.getByLabel('充电 A 月份',{exact:true}).fill('2026-08');
    await page.getByLabel('充电 A 月份',{exact:true}).blur();
    await page.waitForFunction(()=>document.querySelectorAll('[data-charge-chart]').length===0);
    assert.equal(await page.locator('[data-charge-chart]').count(),0,'Condition changes clear previous results after date editor completes');
    console.log('UI_CHARGE_COMPARISON_PASS: month/session selection, common SOC, separate AC/DC/source labels, plateau timing, three responsive plots, point inspection, gaps and error preservation; no writes/cloud');
  }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
