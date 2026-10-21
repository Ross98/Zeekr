const assert = require('node:assert/strict');
const {fixture} = require('./ui_insight_helpers.cjs');

(async () => {
  const f = await fixture(), {page} = f;
  try {
    assert.equal(await page.locator('[data-insight-view]').count(),1);
    assert.equal(await page.locator('.insight-navigation').isVisible(),false,'No tool directory for a single retained workspace');
    await page.locator('#field-results').waitFor();
    await page.getByRole('button', {name:'用车账本',exact:true}).click();
    await page.getByRole('button', {name:'充电账本',exact:true}).click();
    await page.getByRole('button',{name:'读取账本',exact:true}).click();
    await page.getByRole('button',{name:'新增账单',exact:true}).click();
    assert.equal(await page.locator('#ledger-note').isVisible(),false,'Optional bill fields default to collapsed');
    await page.locator('[data-detail="ledger-extras"] > summary').click();
    await page.locator('#ledger-note').fill('本地未保存草稿');
    await page.evaluate(() => render());
    assert.equal(await page.locator('#ledger-note').inputValue(), '本地未保存草稿');
    await page.getByRole('button', {name:'生活账本',exact:true}).click();
    await page.getByRole('button', {name:'充电账本',exact:true}).click();
    assert.equal(await page.locator('#ledger-note').inputValue(), '本地未保存草稿');

    await page.getByRole('button', {name:'用车研究',exact:true}).click();
    assert.equal(await page.locator('[data-insight-view="ledger"]').count(), 0);
    await page.locator('#search').fill('chargeLevel');
    await page.evaluate(() => {state.insights_context='synthetic-other-owner';render();});
    assert.equal(await page.locator('#search').inputValue(), '');
    assert.deepEqual(f.errors, []);
    console.log('UI_INSIGHTS_NAVIGATION_PASS: desktop grouping, search, section switching, draft preservation and account isolation');
  } finally {await f.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
