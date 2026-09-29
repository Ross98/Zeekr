const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture(),{page}=f;
  try{
    await page.getByRole('button',{name:'设置',exact:true}).first().click();
    await page.getByRole('button',{name:'自定义提醒',exact:true}).click();
    assert.match(await page.locator('#rule-delivery').innerText(),/Bark.*企业微信兜底/);
    await page.getByLabel('提醒名称',{exact:true}).fill('<img src=x onerror=alert(1)> 合成规则');
    await page.getByLabel('电量阈值（%）',{exact:true}).fill('30');
    await page.getByLabel('连续确认（秒）',{exact:true}).fill('120');
    await page.getByLabel('冷却时间（分钟）',{exact:true}).fill('60');
    await page.getByLabel('启用这条规则',{exact:true}).check();
    await page.evaluate(()=>render());
    assert.equal(await page.getByLabel('提醒名称',{exact:true}).inputValue(),'<img src=x onerror=alert(1)> 合成规则');
    await page.getByRole('button',{name:'预览条件',exact:true}).click();
    await page.locator('#rule-preview-result').waitFor();
    assert.match(await page.locator('#rule-preview-result').innerText(),/预览不会|不计入/);
    await page.getByRole('button',{name:'保存规则',exact:true}).click();
    await page.waitForFunction(()=>[...document.querySelectorAll('[data-rule-record]')].some(el=>el.textContent.includes('合成规则')));
    const record=page.locator('[data-rule-record]').filter({hasText:'合成规则'});
    assert.equal(await record.locator('img').count(),0);
    assert.match(await record.innerText(),/120 秒/);
    await record.getByRole('button',{name:'停用规则',exact:true}).click();
    await record.getByRole('button',{name:'启用规则',exact:true}).waitFor();
    await page.getByRole('button',{name:'撤销规则操作',exact:true}).click();
    await record.getByRole('button',{name:'停用规则',exact:true}).waitFor();
    await record.getByRole('button',{name:'编辑规则',exact:true}).click();
    await page.getByLabel('提醒名称',{exact:true}).fill('更新后的合成规则');
    await page.getByRole('button',{name:'保存规则',exact:true}).click();
    await page.locator('[data-rule-record]').filter({hasText:'更新后的合成规则'}).waitFor();
    await record.getByRole('button',{name:'删除规则',exact:true}).click();
    await page.getByRole('button',{name:'恢复规则',exact:true}).click();
    await page.locator('[data-rule-record]').filter({hasText:'更新后的合成规则'}).waitFor();
    await page.getByRole('button',{name:'新建规则',exact:true}).click();
    await page.getByLabel('提醒名称',{exact:true}).fill('车窗待核验');
    await page.getByLabel('提醒条件',{exact:true}).selectOption('parked_windows');
    await page.getByLabel('启用这条规则',{exact:true}).check();
    await page.getByRole('button',{name:'保存规则',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'打开枚举尚未核验'}).waitFor();
    assert.equal(await page.getByLabel('提醒名称',{exact:true}).inputValue(),'车窗待核验');
    await page.getByLabel('启用这条规则',{exact:true}).uncheck();
    await page.getByRole('button',{name:'保存规则',exact:true}).click();
    await page.locator('[data-rule-record]').filter({hasText:'车窗待核验'}).waitFor();
    assert.ok(await page.locator('[data-rule-history]').count()>0);
    await layouts(page,'custom-reminders');
    await page.reload();
    await page.getByRole('button',{name:'设置',exact:true}).first().click();
    await page.getByRole('button',{name:'自定义提醒',exact:true}).click();
    await page.locator('[data-rule-record]').filter({hasText:'更新后的合成规则'}).waitFor();
    const refresh=page.waitForResponse(r=>r.url()===f.origin+'/api/insights/rules'&&r.request().method()==='GET');
    await page.evaluate(async()=>{const real=Date.now;Date.now=()=>real()+31000;try{await pollState(true);}finally{Date.now=real;}});
    await refresh;
    // A context-only change must clear previous account content even if all
    // vehicle metrics, revision and timestamps happen to be identical.
    await page.route('**/api/state',async route=>{
      const response=await route.fetch(),state=await response.json();
      await route.fulfill({json:{...state,insights_context:'different-account-context'}});
    });
    await page.evaluate(()=>pollState(true));
    assert.equal(await page.locator('[data-rule-record]').count(),0);
    assert.ok(f.posts.every(url=>url.startsWith(f.origin+'/api/insights/rules')));
    assert.deepEqual(f.external,[]);assert.deepEqual(f.errors,[]);
    console.log('UI_CUSTOM_REMINDERS_PASS: preview/create/edit/enable/disable/undo/delete/restore, unverified-window guard, synthetic history, persistence, XSS, form preservation, themes/mobile/zoom/contrast');
  }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
