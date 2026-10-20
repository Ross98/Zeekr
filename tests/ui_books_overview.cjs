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
  changed=await write('/api/insights/life',{collection:'expenses',action:'save',revision:changed.revision,context:book.context,date:'2026-09-19',category:'轮胎整备',title:'轮胎整备',amount:'10',note:''});
  for(let i=1;i<=12;i++)changed=await write('/api/insights/life',{collection:'expenses',action:'save',revision:changed.revision,context:book.context,date:'2022-01-'+String(i).padStart(2,'0'),category:'旧保养',title:'历史费用 '+i,amount:'1',note:''});
 });
 await page.getByRole('button',{name:'用车账本',exact:true}).click();await page.getByRole('button',{name:'费用总览',exact:true}).click();await page.locator('#books-month').fill('2026-09');await page.getByRole('button',{name:'读取费用总览',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#books-totals strong')?.textContent==='40.00 元');assert.equal(await page.locator('#books-totals strong').first().innerText(),'40.00 元');await page.getByText(/可能重复录入停车费 1 笔/).waitFor();await page.getByRole('heading',{name:'近半年花费',exact:true}).waitFor();
 const panels=await page.locator('[data-books-panel]').evaluateAll(es=>es.map(el=>{const r=el.getBoundingClientRect();return {kind:el.dataset.booksPanel,top:r.top,bottom:r.bottom,width:r.width};}));
 assert.deepEqual(panels.map(p=>p.kind),['categories','largest','trend','timeline']);
 assert.equal(panels[0].top,panels[1].top);assert.equal(panels[0].bottom,panels[1].bottom);
 assert.ok(panels[2].top>panels[0].bottom&&panels[3].top>panels[2].bottom);
 assert.deepEqual(await page.locator('[data-cost-category]').allTextContents(),['充电','轮胎整备','停车','充电停车费']);
 assert.match(await page.locator('[data-books-panel=largest]').innerText(),/25.00 元/);
 assert.equal(await page.locator('[data-cost-month]').count(),6);


 await page.getByRole('button',{name:'筛选分类 轮胎整备',exact:true}).click();
 assert.equal(await page.locator('[data-books-record]').count(),1);assert.match(await page.locator('[data-books-record]').innerText(),/轮胎整备.*10.00/s);
 await page.getByRole('button',{name:'全部分类',exact:true}).click();
 assert.equal(await page.locator('[data-books-record]').count(),4);
 await layouts(page,'books-overview');
 await page.getByRole('button',{name:'全部历史',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#books-totals strong')?.textContent==='52.00 元');
 assert.equal(await page.locator('[data-cost-month]').count(),12);
 await page.getByRole('heading',{name:'历史最大单笔',exact:true}).waitFor();
 await page.getByRole('heading',{name:'历史支出足迹',exact:true}).waitFor();
 await layouts(page,'books-all-history');
 await page.getByLabel('花费年份',{exact:true}).selectOption('2022');
 await page.waitForFunction(()=>document.querySelector('[data-cost-month="2022-01"]'));
 assert.equal(await page.locator('#books-totals strong').first().innerText(),'52.00 元');
 await page.getByRole('button',{name:'筛选分类 旧保养',exact:true}).click();
 await page.getByRole('button',{name:'展开更多支出',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('[data-books-record]').length===10);
 await page.getByRole('button',{name:'下一页费用',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('[data-books-record]').length===2);
 await page.getByRole('button',{name:'本月',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#books-totals strong')?.textContent==='40.00 元');
 assert.equal(await page.locator('[data-cost-month]').count(),6);
 let releaseAll;
 const holdAll=async route=>{if(new URL(route.request().url()).searchParams.get('scope')==='all')await new Promise(resolve=>{releaseAll=resolve;});await route.continue();};
 await page.route('**/api/insights/costs?**',holdAll);
 const started=page.waitForRequest(r=>r.url().includes('/api/insights/costs?')&&new URL(r.url()).searchParams.get('scope')==='all');
 await page.getByRole('button',{name:'全部历史',exact:true}).click();await started;
 await page.getByRole('button',{name:'本月',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#books-totals strong')?.textContent==='40.00 元');
 const finished=page.waitForResponse(r=>r.url().includes('/api/insights/costs?')&&new URL(r.url()).searchParams.get('scope')==='all');releaseAll();await finished;
 await page.evaluate(()=>new Promise(requestAnimationFrame));
 assert.equal(await page.locator('#books-totals strong').first().innerText(),'40.00 元','late cumulative response cannot overwrite monthly selection');
 await page.unroute('**/api/insights/costs?**',holdAll);


 await page.getByRole('button',{name:'实际金额待补 1 笔',exact:true}).click();await page.locator('#ledger-range').waitFor();assert.equal(await page.getByLabel('账单筛选',{exact:true}).inputValue(),'unknown');assert.equal(await page.locator('[data-ledger-entry]').count(),1);
 await page.getByRole('button',{name:'编辑账单',exact:true}).click();await page.locator('#ledger-note').fill('待处理草稿');await page.getByRole('button',{name:'新增账单',exact:true}).click();assert.equal(await page.locator('#ledger-note').inputValue(),'待处理草稿');await page.getByRole('button',{name:'放弃草稿，继续',exact:true}).click();assert.equal(await page.locator('#ledger-note').inputValue(),'');await page.getByRole('button',{name:'取消新增',exact:true}).click();
 await page.getByRole('button',{name:'费用总览',exact:true}).click();await page.locator('#books-totals').waitFor();await page.getByRole('button',{name:'查看日常支出',exact:true}).click();await page.locator('#life-total').waitFor();assert.equal(await page.locator('#life-start').inputValue(),'2026-09-01');assert.equal(await page.locator('#life-end').inputValue(),'2026-09-30');assert.equal(await page.locator('#life-form').count(),0);await layouts(page,'books-life-list');
 await page.getByRole('button',{name:'新增支出',exact:true}).click();await page.getByLabel('支出名称',{exact:true}).fill('保留生活草稿');await page.getByRole('button',{name:'取消编辑',exact:true}).click();await page.getByRole('button',{name:'继续编辑草稿',exact:true}).click();assert.equal(await page.getByLabel('支出名称',{exact:true}).inputValue(),'保留生活草稿');
 assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);console.log('BOOKS_OVERVIEW_UI_PASS: totals, estimates, duplicate hints, unknown bills, safe discard, month navigation, collapsed life editor, desktop layouts');
}finally{await f.close()}})().catch(e=>{console.error(e);process.exitCode=1});
