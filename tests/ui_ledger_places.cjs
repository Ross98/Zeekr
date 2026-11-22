const assert=require('node:assert/strict');
const fs=require('node:fs');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture({chargingPlaces:true}),{page}=f;
  const amount=()=>page.getByLabel('实际账单金额（元）',{exact:true});
  const save=()=>page.getByRole('button',{name:'保存账单',exact:true}).click();
  const read=()=>page.evaluate(()=>fetch('/api/insights/ledger?date=2026-09-20').then(r=>r.json()));
  const open=async id=>{
    const data=await read(),bill=data.entries.find(row=>row.source_event_id===id);
    if(bill)await page.locator(`[data-ledger="edit"][data-id="${bill.id}"]`).click();
    else await page.locator(`[data-ledger="pending-new"][data-id="${id}"]`).click();
    await page.getByLabel('充电地点',{exact:true}).waitFor();
    await page.getByLabel('充电地点',{exact:true}).focus();
  };
  try{
    await page.getByRole('button',{name:'用车账本',exact:true}).first().click();
    await page.getByRole('button',{name:'充电账本',exact:true}).click();
    await page.getByLabel('账本月份',{exact:true}).fill('2026-09');
    await page.getByRole('button',{name:'读取账本',exact:true}).click();
    await page.locator('#ledger-range').waitFor();
    await open('report-charge');
    assert.equal(await page.getByLabel('充电地点',{exact:true}).inputValue(),'');
    assert.ok((await page.getByLabel('充电地点',{exact:true}).locator('option').allTextContents()).includes('测试广场'));
    await page.getByLabel('充电地点',{exact:true}).selectOption('new:');
    await page.getByLabel('新充电地点',{exact:true}).fill('合成新地点 <b>');
    await page.getByLabel('充电站',{exact:true}).selectOption('new:');
    await page.getByLabel('新充电站',{exact:true}).fill('合成新站 <img>');
    await amount().fill('12.34');
    await page.evaluate(()=>render());
    assert.equal(await page.getByLabel('新充电地点',{exact:true}).inputValue(),'合成新地点 <b>');
    assert.equal(await page.getByLabel('新充电站',{exact:true}).inputValue(),'合成新站 <img>');
    await page.reload();
    await page.getByLabel('新充电站',{exact:true}).waitFor();
    assert.equal(await page.getByLabel('新充电地点',{exact:true}).inputValue(),'合成新地点 <b>');
    assert.equal(await page.getByLabel('新充电站',{exact:true}).inputValue(),'合成新站 <img>');
    assert.equal(await amount().inputValue(),'12.34');
    await page.getByLabel('账本月份',{exact:true}).fill('2026-08');
    await page.getByLabel('账本月份',{exact:true}).blur();
    await page.waitForFunction(()=>document.querySelector('#ledger-range')?.textContent.includes('2026-08'));
    assert.equal(await page.getByLabel('新充电站',{exact:true}).inputValue(),'合成新站 <img>');
    assert.equal(await page.getByLabel('关联充电记录',{exact:true}).inputValue(),'report-charge');
    fs.mkdirSync('/tmp/zeekr-insights-qa',{recursive:true});
    for(const width of [1440,1280,1024]){
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      assert.equal(await page.getByLabel('新充电站',{exact:true}).isVisible(),true);
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('#ledger-editor').screenshot({path:'/tmp/zeekr-insights-qa/ledger-places-editor.png'});
    await save();
    await page.waitForFunction(()=>!document.querySelector('#ledger-form'));
    let data=await read(),bill=data.entries.find(row=>row.source_event_id==='report-charge');
    assert.equal(bill.actual_cents,1234);
    assert.equal(bill.event.station_name,'合成新站 <img>');
    assert.equal(bill.event.place_label,'合成新地点 <b>');
    assert.equal(await page.locator('[data-ledger-entry] img,[data-ledger-entry] b').count(),0);
    // A second charge can choose the saved venue and associated station.
    await open('place-repeat');
    await page.getByLabel('充电地点',{exact:true}).selectOption('history:合成新地点 <b>');
    assert.equal(await page.getByLabel('充电站',{exact:true}).inputValue(),'history:合成新站 <img>');
    await amount().fill('0');
    await save();await page.waitForFunction(()=>!document.querySelector('#ledger-form'));
    data=await read();bill=data.entries.find(row=>row.source_event_id==='place-repeat');
    assert.equal(bill.actual_cents,0);assert.equal(bill.event.station_name,'合成新站 <img>');
    // A stale place revision rejects the entire save and retains the draft.
    await open('place-unknown');
    await page.getByLabel('充电地点',{exact:true}).selectOption('history:合成新地点 <b>');
    await amount().fill('9');
    await page.evaluate(async()=>{
      const options=await fetch('/api/insights/ledger?date=2026-09-20').then(r=>r.json());
      const bill=options.entries.find(row=>row.source_event_id==='report-charge');
      const response=await fetch('/api/insights/ledger',{method:'POST',headers:{'Content-Type':'application/json','X-Request-Key':state.request_key},body:JSON.stringify({action:'save',id:bill.id,event_id:'report-charge',date:'2026-09-19',source:'public',amount:'12.34',revision:options.revision,context:state.insights_context,place_correction:{revision:options.place_choices.revision,name:'另一个合成地点',station_name:'另一个合成站'}})});
      if(!response.ok)throw Error('Fixture concurrent update failed');
    });
    await save();await page.getByText(/填写内容保留/).waitFor();
    assert.equal(await amount().inputValue(),'9');
    assert.equal(await page.getByLabel('充电地点',{exact:true}).inputValue(),'history:合成新地点 <b>');
    data=await read();assert.equal(data.entries.some(row=>row.source_event_id==='place-unknown'),false);
    await page.getByRole('button',{name:'读取账本',exact:true}).click();
    await page.getByRole('button',{name:'已核对列表，继续编辑',exact:true}).click();
    await save();await page.waitForFunction(()=>!document.querySelector('#ledger-form'));
    data=await read();assert.equal(data.entries.find(row=>row.source_event_id==='place-unknown').event.station_name,'合成新站 <img>');
    assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
    console.log('UI_LEDGER_PLACES_PASS: new names, historical paired dropdowns, atomic conflict, draft preservation, zero bill, escaped labels, desktop widths');
  }catch(error){await f.fail(error);throw error;}finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
