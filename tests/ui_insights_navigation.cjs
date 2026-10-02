const assert = require('node:assert/strict');
const {fixture} = require('./ui_insight_helpers.cjs');

(async () => {
  const f = await fixture(), {page} = f;
  try {
    assert.equal(await page.locator('[data-insight-group]').count(), 2);
    assert.equal(await page.locator('[data-insight-view]').count(), 7);
    const search = page.getByLabel('查找研究工具', {exact:true});
    await search.fill('归档');
    assert.deepEqual(await page.locator('[data-insight-view]:visible').allTextContents(), ['车辆时间机']);
    await page.evaluate(() => render());
    assert.equal(await search.inputValue(), '归档');
    await page.getByRole('button', {name:'车辆时间机',exact:true}).click();
    assert.equal(await search.inputValue(), '');

    await page.getByRole('button', {name:'能源与充电',exact:true}).click();
    await page.getByRole('button', {name:'充电账本',exact:true}).click();
    await page.getByRole('button',{name:'读取账本',exact:true}).click();
    await page.getByRole('button',{name:'新增账单',exact:true}).click();
    await page.locator('#ledger-note').fill('本地未保存草稿');
    await page.evaluate(() => render());
    assert.equal(await page.locator('#ledger-note').inputValue(), '本地未保存草稿');
    await page.getByRole('button', {name:'充电曲线对比',exact:true}).click();
    await page.getByRole('button', {name:'充电账本',exact:true}).click();
    assert.equal(await page.locator('#ledger-note').inputValue(), '本地未保存草稿');

    await page.getByRole('button', {name:'用车研究',exact:true}).click();
    assert.equal(await page.locator('[data-insight-view="ledger"]').count(), 0);
    await search.fill('归档');
    await page.evaluate(() => {state.insights_context='synthetic-other-owner';render();});
    assert.equal(await search.inputValue(), '');
    assert.deepEqual(f.errors, []);
    console.log('UI_INSIGHTS_NAVIGATION_PASS: desktop grouping, search, section switching, draft preservation and account isolation');
  } finally {await f.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
