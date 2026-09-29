const assert = require('node:assert/strict');
const {fixture} = require('./ui_insight_helpers.cjs');

(async () => {
  const f = await fixture();
  const {page} = f;
  try {
    const groups = [
      ['能源与充电', ['充电曲线对比', '充电账本', '停车耗电']],
      ['行程与轨迹', ['行程标签', '行程卡片']],
      ['车辆', ['车辆时间机', '生活账本']],
      ['设置', ['自定义提醒']],
      ['用车研究', ['数据利用', '自动洞察', '参数实验室', '数据质量雷达', '周报与月报', '用车日历']]
    ];
    for (const [section, labels] of groups) {
      await page.getByRole('button', {name:section, exact:true}).first().click();
      const tools = page.locator('#insights-workspace [data-insight-view]');
      assert.deepEqual(await tools.allTextContents(), labels, `${section} tools`);
      if(section!=='用车研究')assert.deepEqual(await page.locator('.related-tools a').allTextContents(),labels,`${section} shortcuts`);
      if(section!=='用车研究')assert.equal(await page.locator('#insights-workspace [aria-pressed="true"]').count(),0);
      await tools.first().click();
      assert.equal(await tools.first().getAttribute('aria-pressed'), 'true');
    }
    await page.getByRole('button', {name:'能源与充电', exact:true}).first().click();
    await page.getByRole('button', {name:'充电曲线对比', exact:true}).click();
    await page.getByLabel('充电 A 月份', {exact:true}).waitFor();
    await page.getByRole('button', {name:'用车研究',exact:true}).click();
    await page.getByRole('button', {name:'用车日历',exact:true}).click();
    await page.locator('[data-calendar-day="2026-09-19"]').click();
    await page.getByRole('button', {name:'查看当日快照',exact:true}).click();
    assert.equal(await page.locator('#insights-workspace [data-insight-view="time"]').getAttribute('aria-pressed'),'true');
    assert.equal(await page.getByLabel('归档日期',{exact:true}).inputValue(),'2026-09-19');
    await page.getByRole('button', {name:'用车研究',exact:true}).click();
    await page.getByRole('button', {name:'用车日历',exact:true}).click();
    await page.locator('[data-calendar-day="2026-09-19"]').click();
    await page.getByRole('button', {name:'查看当日停车片段',exact:true}).click();
    assert.equal(await page.locator('#insights-workspace [data-insight-view="parking"]').getAttribute('aria-pressed'),'true');
    assert.deepEqual(f.errors, []);
    console.log('UI_TOOL_NAVIGATION_PASS');
  } finally { await f.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
