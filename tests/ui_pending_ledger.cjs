const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture({partialCharge:true}),{page}=f;
  try{
    // Enrich only the synthetic list to exercise paging. Saving the original
    // event still reaches the real local ledger and revision checks.
    await page.route('**/api/insights/ledger?*',async route=>{
      const response=await route.fetch(),data=await response.json();
      if(data.window.start_date.startsWith('2026-09')){
        data.events=[...Array.from({length:20},(_,index)=>({
          id:`synthetic-pending-${index}`,end_time:Date.UTC(2026,8,1,16)+index*3600000,
          start_soc:null,end_soc:null,partial:true,recorded:false})),...data.events];
      }
      await route.fulfill({json:data});
    });
    if(await page.getByRole('button',{name:'能源与充电',exact:true}).first().isVisible())
      await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
    await page.getByRole('button',{name:'充电账本',exact:true}).click();
    await page.getByLabel('账本月份',{exact:true}).fill('2026-09');
    await page.getByRole('button',{name:'读取账本',exact:true}).click();
    await page.getByRole('button',{name:'去补账',exact:true}).click();
    assert.equal(await page.locator('[data-ledger="pending-new"]').count(),10);
    assert.match(await page.locator('#ledger-pending-list').innerText(),/片段.*—% → —%/s);
    await layouts(page,'pending-ledger');
    await page.getByRole('button',{name:'下一页待补账',exact:true}).click();
    await page.getByRole('button',{name:'下一页待补账',exact:true}).click();
    assert.match(await page.locator('#ledger-pending .insight-pagination').innerText(),/3 \/ 3/);
    assert.equal(await page.locator('[data-ledger="pending-new"]').count(),1);
    await page.locator('#ledger-pending').scrollIntoViewIfNeeded();
    const position=await page.evaluate(()=>scrollY);
    await page.locator('[data-ledger="pending-new"][data-id="report-charge"]').click();
    assert.equal(await page.getByLabel('账单日期',{exact:true}).inputValue(),'2026-09-19');
    assert.equal(await page.getByLabel('实际账单金额（元）',{exact:true}).inputValue(),'');
    await page.getByLabel('实际账单金额（元）',{exact:true}).fill('0');
    await page.evaluate(()=>render());
    assert.equal(await page.getByLabel('实际账单金额（元）',{exact:true}).inputValue(),'0','rerender retains zero draft');
    await page.getByRole('button',{name:'保存账单',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#ledger-pending')?.textContent.includes('20 次待记账'));
    assert.match(await page.locator('#ledger-pending .insight-pagination').innerText(),/2 \/ 2/,'page clamps after last row removed');
    assert.equal(await page.locator('#ledger-form').count(),0);
    assert.equal(await page.getByLabel('账本月份',{exact:true}).inputValue(),'2026-09');
    assert.ok(Math.abs(await page.evaluate(()=>scrollY)-position)<2,'save returns to list position');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'ledger-pending-count','keyboard focus returns to updated count');
    assert.match(await page.locator('#ledger-actual-total').innerText(),/0\.00/);
    await page.getByRole('button',{name:'撤销上一步',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#ledger-pending')?.textContent.includes('21 次待记账'));
    assert.match(await page.locator('#ledger-pending .insight-pagination').innerText(),/2 \/ 3/,'undo keeps current page');
    await page.getByRole('button',{name:'下一页待补账',exact:true}).click();
    await page.locator('[data-ledger="pending-new"][data-id="report-charge"]').click();
    await page.getByRole('button',{name:'取消新增',exact:true}).click();
    assert.match(await page.locator('#ledger-pending .insight-pagination').innerText(),/3 \/ 3/);
    const owner=await page.evaluate(()=>state.insights_context);
    await page.locator('[data-ledger="pending-new"][data-id="report-charge"]').click();
    await page.getByLabel('实际账单金额（元）',{exact:true}).fill('12');
    await page.evaluate(()=>{state.insights_context='synthetic-other-owner';render();});
    assert.equal(await page.locator('#ledger-form').count(),0,'account switch clears pending draft');
    assert.equal(await page.locator('#ledger-pending').count(),0,'account switch clears pending list');
    await page.evaluate(owner=>{state.insights_context=owner;render();},owner);
    await page.getByRole('button',{name:'读取账本',exact:true}).click();
    await page.getByRole('button',{name:'去补账',exact:true}).waitFor();
    assert.equal(await page.locator('[data-ledger="pending-new"]').count(),0,'new account context starts with collapsed list');
    await page.getByLabel('账本月份',{exact:true}).fill('2026-08');
    await page.getByRole('button',{name:'读取账本',exact:true}).click();
    await page.getByText('本月没有结束充电记录',{exact:true}).waitFor();
    assert.equal(await page.locator('[data-ledger="pending-new"]').count(),0,'month change removes previous pending records');
    assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
    assert.ok(f.posts.every(url=>url===f.origin+'/api/insights/ledger'));
    console.log('UI_PENDING_LEDGER_PASS: partial/unknown records, paging, date prefill, real zero-cost save, page clamp, scroll return, undo, cancel, month isolation, layouts');
  }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
