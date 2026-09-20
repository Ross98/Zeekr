const assert = require('node:assert/strict');
const {fixture, layouts} = require('./ui_insight_helpers.cjs');
(async () => {
  const f = await fixture(), {page} = f;
  page.setDefaultTimeout(10000);
  const tool = name => page.getByRole('button', {name, exact: true});
  try {
    assert.equal(await page.locator('[data-insight-group]').count(), 4);
    assert.equal(await page.locator('[data-insight-view]').count(), 14);
    const search = page.getByLabel('查找研究工具', {exact: true});
    await search.fill('费用');
    assert.equal(await page.locator('[data-insight-view]:visible').count(), 2);
    assert.equal(await search.evaluate(el => el === document.activeElement), true);
    await page.evaluate(() => render());
    assert.equal(await search.inputValue(), '费用');
    await search.fill('不存在的工具');
    await page.getByText('没有匹配的工具，试试「充电」「费用」「行程」。', {exact: true}).waitFor();
    assert.equal(await page.locator('[data-insight-view]:visible').count(), 0);
    await tool('清空工具搜索').click();
    assert.equal(await page.locator('[data-insight-view]:visible').count(), 14);
    assert.equal(await search.evaluate(el => el === document.activeElement), true);
    await search.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'insight-tool-clear');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.insightView), 'research');
    await page.keyboard.press('Enter');

    await tool('充电账本').click();
    await page.locator('#ledger-note').fill('本地未保存草稿');
    await page.evaluate(() => {window.navigationDraftNode = document.querySelector('#ledger-note');});
    await tool('充电账本').click();
    assert.equal(await page.evaluate(() => window.navigationDraftNode === document.querySelector('#ledger-note')), true, 'Clicking the current tool preserves the workspace DOM');
    await search.fill('质量');
    await tool('数据质量雷达').click();
    assert.equal(await search.inputValue(), '', 'A successful tool selection clears the temporary search');
    assert.equal(await tool('数据质量雷达').getAttribute('aria-pressed'), 'true');
    await tool('充电账本').click();
    assert.equal(await page.locator('#ledger-note').inputValue(), '本地未保存草稿');

    await layouts(page, 'insights-navigation');
    for (const width of [390, 320]) {
      await page.setViewportSize({width, height: 900});
      assert.ok(await page.locator('.insight-navigation').evaluate(el => el.getBoundingClientRect().height < 125), 'Compact mobile tool selector');
      for (const [value,label] of [['automatic','自动洞察'],['time','车辆时间机'],['report','周报与月报'],['parking','停车耗电']]) {
        await page.getByLabel('当前研究工具',{exact:true}).selectOption(value);
        assert.equal(await page.getByLabel('当前研究工具',{exact:true}).inputValue(),value);
        await tool('查找工具').click();
        assert.equal(await tool(label).getAttribute('aria-pressed'),'true');
        await tool('查找工具').click();
      }
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    await page.setViewportSize({width: 1440, height: 1000});
    await page.evaluate(() => {document.documentElement.style.zoom = '2';});
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.ok(await page.getByLabel('当前研究工具',{exact:true}).isVisible(), 'Current tool selector visible at 200% zoom');
    await page.evaluate(() => {document.documentElement.style.zoom = '';});
    await search.fill('费用');
    await page.evaluate(() => {state.insights_context = 'synthetic-other-owner'; render();});
    assert.equal(await search.inputValue(), '', 'Account changes clear navigation search');
    assert.deepEqual(f.posts, []);
    assert.deepEqual(f.external, []);
    assert.deepEqual(f.errors, []);
    console.log('UI_INSIGHTS_NAVIGATION_PASS: grouped search, empty/reset/focus, no-op active selection, drafts, mobile navigation, owner isolation, themes/zoom/contrast');
  } finally {await f.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
