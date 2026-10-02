const assert = require('node:assert/strict');
const {fixture} = require('./ui_insight_helpers.cjs');

(async () => {
  const f = await fixture();
  const {page} = f;
  try {
    assert.equal(await page.locator('#navigation [data-page="fields"]').count(),0);
    const groups = [
      ['能源与充电', ['充电账本', '充电曲线对比']],
      ['行程与轨迹', []],
      ['车辆', ['生活账本']],
      ['设置', ['自定义提醒', '数据质量雷达']],
      ['用车研究', ['参数字典', '数据利用', '自动洞察', '参数实验室', '车辆时间机', '周报与月报', '用车日历']]
    ];
    for (const [section, labels] of groups) {
      await page.getByRole('button', {name:section, exact:true}).first().click();
      const research=section==='用车研究';
      const tools=research?page.locator('#insights-workspace [data-insight-view]'):page.locator('.task-navigation [data-section-task]').filter({hasText:new RegExp(labels.join('|')||'^$')});
      assert.deepEqual(await tools.allTextContents(),labels,`${section} tools`);
      if(!research&&labels.length){
        assert.equal(await page.locator('#insights-workspace').isVisible(),false);
        await tools.first().click();
        assert.equal(await tools.first().getAttribute('aria-pressed'),'true');
        assert.equal(await page.locator('#insights-workspace').isVisible(),true);
        assert.equal(await page.locator('#insights-workspace .insight-navigation').isVisible(),false);
      } else if(research){await tools.first().click();}
      assert.equal(await page.getByRole('button',{name:'行程卡片',exact:true}).count(),0);
    }
    await page.getByRole('button',{name:'参数字典',exact:true}).click();
    await page.locator('#field-results').waitFor();
    assert.equal(await page.locator('#navigation [data-page="insights"]').getAttribute('aria-current'),'page');
    await page.getByRole('button', {name:'行程与轨迹',exact:true}).first().click();
    await page.locator('.related-tools [data-track-tags]').click();
    assert.equal(await page.getByRole('heading',{name:'通勤自动标注'}).count(),1);
    await page.getByRole('button', {name:'能源与充电', exact:true}).first().click();
    await page.getByRole('button', {name:'充电曲线对比', exact:true}).click();
    await page.getByLabel('充电 A 月份', {exact:true}).waitFor();
    await page.getByRole('button', {name:'用车研究',exact:true}).click();
    await page.getByRole('button', {name:'用车日历',exact:true}).click();
    await page.getByLabel('日历月份',{exact:true}).fill('2026-09');
    await page.getByRole('button',{name:'读取用车日历',exact:true}).click();
    await page.locator('[data-calendar-day="2026-09-19"]').click();
    await page.getByRole('button', {name:'查看当日快照',exact:true}).click();
    assert.equal(await page.locator('#insights-workspace [data-insight-view="time"]').getAttribute('aria-pressed'),'true');
    assert.equal(await page.getByLabel('归档日期',{exact:true}).inputValue(),'2026-09-19');
    assert.equal(await page.locator('[data-insight-view="parking"]').count(),0);
    await page.setViewportSize({width:390,height:844});
    await page.locator('#mobile-navigation [data-page="more"]').click();
    assert.equal(await page.locator('main [data-page="fields"]').count(),0);
    await page.locator('main [data-page="insights"]').click();
    await page.getByLabel('当前研究工具',{exact:true}).selectOption('fields');
    await page.locator('#field-results').waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.deepEqual(f.errors, []);
    console.log('UI_TOOL_NAVIGATION_PASS');
  } finally { await f.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
