const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{const f=await fixture(),{page}=f;try{
 await page.evaluate(async()=>{
  const write=async(url,body)=>{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Request-Key':state.request_key},body:JSON.stringify(body)});if(!r.ok)throw Error(JSON.stringify(await r.json()));return r.json()};
  let book=await fetch('/api/insights/ledger?date=2026-09-01').then(r=>r.json());
  let changed=await write('/api/insights/ledger',{action:'save',revision:book.revision,context:book.context,event_id:'',date:'2026-09-19',source:'public',amount:'20',parking_fee:'5',note:'测试充电'});
  await write('/api/insights/ledger',{action:'save',revision:changed.revision,context:book.context,event_id:'report-charge',date:'2026-09-19',source:'home',amount:'',metered_kwh:'50',unit_price:'0.7',note:'实际金额待补'});
  book=await fetch('/api/insights/life?start=2026-09-01&end=2026-09-30').then(r=>r.json());
  changed=await write('/api/insights/life',{collection:'expenses',action:'save',revision:book.expenses.revision,context:book.context,date:'2026-09-19',category:'停车',title:'可能重复停车费',amount:'5',note:''});
  await write('/api/insights/life',{collection:'expenses',action:'save',revision:changed.revision,context:book.context,date:'2026-09-19',category:'洗车',title:'洗车',amount:'10',note:''});
 });
 await page.getByRole('button',{name:'用车账本',exact:true}).click();await page.getByRole('button',{name:'费用总览',exact:true}).click();await page.locator('#books-month').fill('2026-09');await page.getByRole('button',{name:'读取费用总览',exact:true}).click();await page.locator('#books-totals').waitFor();assert.equal(await page.locator('#books-totals strong').first().innerText(),'40.00 元');await page.getByText(/可能重复录入停车费 1 笔/).waitFor();await layouts(page,'books-overview');
 await page.getByRole('button',{name:'实际金额待补 1 笔',exact:true}).click();await page.locator('#ledger-range').waitFor();assert.equal(await page.getByLabel('账单筛选',{exact:true}).inputValue(),'unknown');assert.equal(await page.locator('[data-ledger-entry]').count(),1);
 await page.getByRole('button',{name:'编辑账单',exact:true}).click();await page.locator('#ledger-note').fill('待处理草稿');await page.getByRole('button',{name:'新增账单',exact:true}).click();assert.equal(await page.locator('#ledger-note').inputValue(),'待处理草稿');await page.getByRole('button',{name:'放弃草稿，继续',exact:true}).click();assert.equal(await page.locator('#ledger-note').inputValue(),'');await page.getByRole('button',{name:'取消新增',exact:true}).click();
 await page.getByRole('button',{name:'费用总览',exact:true}).click();await page.locator('#books-totals').waitFor();await page.getByRole('button',{name:'查看日常支出',exact:true}).click();await page.locator('#life-total').waitFor();assert.equal(await page.locator('#life-start').inputValue(),'2026-09-01');assert.equal(await page.locator('#life-end').inputValue(),'2026-09-30');assert.equal(await page.locator('#life-form').count(),0);await layouts(page,'books-life-list');
 await page.getByRole('button',{name:'新增支出',exact:true}).click();await page.getByLabel('支出名称',{exact:true}).fill('保留生活草稿');await page.getByRole('button',{name:'取消编辑',exact:true}).click();await page.getByRole('button',{name:'继续编辑草稿',exact:true}).click();assert.equal(await page.getByLabel('支出名称',{exact:true}).inputValue(),'保留生活草稿');
 assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);console.log('BOOKS_OVERVIEW_UI_PASS: totals, estimates, duplicate hints, unknown bills, safe discard, month navigation, collapsed life editor, desktop layouts');
}finally{await f.close()}})().catch(e=>{console.error(e);process.exitCode=1});
