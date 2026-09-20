const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture(),{page}=f;
  try{
    await page.getByRole('button',{name:'数据质量雷达',exact:true}).click();
    await page.getByLabel('质量分析开始日期',{exact:true}).fill('2026-09-18');
    await page.getByLabel('质量分析结束日期',{exact:true}).fill('2026-09-21');
    await page.getByRole('button',{name:'分析数据质量',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#quality-range')?.textContent.includes('2026-09-18 至 2026-09-21'));
    assert.equal(await page.locator('[data-quality-day]').count(),4);
    assert.match(await page.locator('#quality-totals').innerText(),/236/);
    assert.match(await page.locator('#quality-totals').innerText(),/重复读取/);
    assert.equal(await page.locator('.quality-delay-row').count(),5);
    assert.match(await page.locator('[data-quality-day="2026-09-21"]').innerText(),/未来日期/);
    await page.locator('[data-quality-day="2026-09-20"]').click();
    assert.match(await page.locator('#quality-gap-heading').innerText(),/2026-09-20/);
    await page.evaluate(()=>render());
    assert.equal(await page.locator('[data-quality-day="2026-09-20"]').getAttribute('aria-pressed'),'true');
    await layouts(page,'data-quality');
    await page.setViewportSize({width:390,height:1000});
    await page.locator('.quality-delays').locator('..').screenshot({path:'/tmp/zeekr-insights-qa/data-quality-delay-dark-390.png'});
    await page.getByRole('button',{name:'查看所选日快照',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#insight-count')?.textContent.includes('2026-09-20'));
    await page.getByLabel('当前研究工具',{exact:true}).selectOption('quality');
    await page.route('**/api/insights/quality?*',r=>r.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'合成归档读取失败'})}));
    await page.getByLabel('质量分析开始日期',{exact:true}).fill('2026-09-01');
    await page.getByRole('button',{name:'分析数据质量',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'合成归档读取失败'}).waitFor();
    assert.match(await page.locator('#quality-range').innerText(),/2026-09-18 至 2026-09-21/);
    assert.deepEqual(f.posts,[]);assert.deepEqual(f.external,[]);assert.deepEqual(f.errors,[]);
    console.log('UI_DATA_QUALITY_PASS: timing composition, delay distribution, daily coverage, future/selected dates, gap filtering, archive navigation, poll/error preservation, themes/mobile/zoom/contrast; read-only');
  }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
