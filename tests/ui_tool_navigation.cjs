const assert = require('node:assert/strict');
const {fixture} = require('./ui_insight_helpers.cjs');

(async () => {
  const f = await fixture();
  const {page} = f;
  try {
    assert.equal(await page.locator('#navigation [data-page="fields"]').count(),0);
    assert.deepEqual(await page.locator('#navigation .navigation-group h2').allTextContents(),['日常用车','回顾与研究','采集与设置']);
    assert.equal(await page.locator('#navigation [data-page]').count(),9);
    assert.deepEqual(await page.locator('.insight-tabs h2').allTextContents(),['数据分析','历史回看','参数核实']);
    const groups = [
      ['能源与充电', ['充电曲线对比', '停车观测']],
      ['用车账本', ['充电账本', '生活账本']],
      ['行程与轨迹', ['常走路线对比']],
      ['车辆', []],
      ['设置', ['自定义提醒', '数据质量雷达']],
      ['用车研究', ['数据利用', '自动洞察', '车辆时间机', '轻量用车回顾', '参数研究与核实']]
    ];
    for (const [section, labels] of groups) {
      await page.getByRole('button', {name:section, exact:true}).first().click();
      const research=section==='用车研究';
      const tools=research?page.locator('#insights-workspace [data-insight-view]'):page.locator('.task-navigation [data-section-task]').filter({hasText:new RegExp(labels.join('|')||'^$')});
      assert.deepEqual(await tools.allTextContents(),labels,`${section} tools`);
      if(!research&&labels.length){
        assert.equal(await page.locator('#insights-workspace').isVisible(),section==='用车账本');
        await tools.first().click();
        assert.equal(await tools.first().getAttribute('aria-pressed'),'true');
        assert.equal(await page.locator('#insights-workspace').isVisible(),true);
        assert.equal(await page.locator('#insights-workspace .insight-navigation').isVisible(),false);
      } else if(research){await tools.first().click();}
      assert.equal(await page.getByRole('button',{name:'行程卡片',exact:true}).count(),0);
    }
    for (const [oldPath,tab] of [['?p=energy&t=ledger&month=2026-09','充电账本'],['?p=car&t=life','生活账本']]) {
      await page.goto(f.origin+oldPath);
      await page.getByRole('heading',{name:'用车账本',exact:true}).waitFor();
      assert.equal(await page.locator('#navigation [data-page="books"]').getAttribute('aria-current'),'page');
      assert.equal(await page.getByRole('button',{name:tab,exact:true}).getAttribute('aria-pressed'),'true');
      await page.reload();
      await page.getByRole('heading',{name:'用车账本',exact:true}).waitFor();
      assert.equal(await page.getByRole('button',{name:tab,exact:true}).getAttribute('aria-pressed'),'true');
    }
    await page.getByRole('button',{name:'用车研究',exact:true}).click();
    await page.getByRole('button',{name:'参数研究与核实',exact:true}).click();
    await page.locator('#field-results').waitFor();
    assert.equal(await page.locator('#navigation [data-page="insights"]').getAttribute('aria-current'),'page');
    await page.getByRole('button', {name:'行程与轨迹',exact:true}).first().click();
    const trackNavigation=page.getByRole('navigation',{name:'行程与轨迹子功能',exact:true});
    assert.deepEqual(await trackNavigation.locator('button').allTextContents(),['本地记录','云端历史','行程标签','常走路线对比']);
    await trackNavigation.getByRole('button',{name:'常走路线对比',exact:true}).click();
    assert.equal(await trackNavigation.getByRole('button',{name:'常走路线对比',exact:true}).getAttribute('aria-pressed'),'true');
    await trackNavigation.getByRole('button',{name:'云端历史',exact:true}).click();
    assert.equal(await trackNavigation.getByRole('button',{name:'云端历史',exact:true}).getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('.track-toolbar [data-source]').count(),0);
    await trackNavigation.getByRole('button',{name:'本地记录',exact:true}).click();
    assert.equal(await trackNavigation.getByRole('button',{name:'本地记录',exact:true}).getAttribute('aria-pressed'),'true');
    await page.locator('.related-tools [data-track-tags]').click();
    assert.equal(await page.getByRole('heading',{name:'通勤自动标注'}).count(),1);
    assert.equal(await page.evaluate(()=>scrollY),0,'task navigation remains available after opening tags');
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
    assert.deepEqual(f.errors, []);
    console.log('UI_TOOL_NAVIGATION_PASS');
  } finally { await f.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
