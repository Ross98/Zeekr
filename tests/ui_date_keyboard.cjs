const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture(),{page}=f;
 try{
  await page.getByRole('button',{name:'车辆',exact:true}).first().click();
  await page.getByRole('button',{name:'生活账本',exact:true}).click();
  const input=page.locator('#life-start');
  await input.focus();
  await input.evaluate(el=>{window.dateInputBefore=el;el.value='';el.dispatchEvent(new Event('input',{bubbles:true}));});
  assert.equal(await input.evaluate(el=>el===window.dateInputBefore&&document.activeElement===el),true,'Partial keyboard date must retain live input and focus');
  await input.evaluate(el=>{el.value='2026-09-01';el.dispatchEvent(new Event('input',{bubbles:true}));});
  const response=page.waitForResponse(r=>r.url().includes('/api/insights/life?'));
  await page.getByRole('button',{name:'查询生活账本',exact:true}).click();
  const loaded=await response;
  assert.ok(loaded.url().includes('start=2026-09-01'));
  assert.equal(loaded.status(),200);
  for(const [section,tool,id] of [
   ['用车日历',null,'calendar-month'],
   ['用车周报',null,'report-date'],
   ['设置','数据质量雷达','quality-start'],
   ['能源与充电','充电账本','ledger-month'],
   ['能源与充电','充电曲线对比','charge-month-a'],
   ['用车研究','车辆时间机','insight-date']
  ]){
   await page.getByRole('button',{name:section,exact:true}).first().click();
   if(tool)await page.getByRole('button',{name:tool,exact:true}).click();
   const date=page.locator('#'+id);
   await date.focus();
   await date.evaluate(el=>{window.dateInputBefore=el;el.value='';el.dispatchEvent(new Event('input',{bubbles:true}));});
   await page.evaluate(()=>render());
   assert.equal(await date.evaluate(el=>el===window.dateInputBefore&&document.activeElement===el),true,id+' survives partial input and polling');
   await date.evaluate(el=>{el.value=el.type==='month'?'2026-09':'2026-09-01';el.dispatchEvent(new Event('input',{bubbles:true}));});
   await date.press('ArrowUp');
   assert.equal(await date.evaluate(el=>el===window.dateInputBefore&&document.activeElement===el),true,id+' survives native keyboard edit');
   await date.blur();
  }
  assert.deepEqual(f.errors,[]);
  console.log('DATE_KEYBOARD_PASS');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
