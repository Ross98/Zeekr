const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
async function ledgerSaveRaces(browser,seed){
 seed.entries=[];seed.trash=[];seed.events.forEach(e=>e.recorded=false);
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.addScriptTag({path:require('node:path').join(__dirname,'../zeekr_control/static/navigation-state.js')});
  await page.addScriptTag({path:require('node:path').join(__dirname,'../zeekr_control/static/charge-ledger.js')});
  for(const boundary of ['account','vehicle','return-to-owner','normal'])for(const phase of boundary==='normal'?['refresh','failed-refresh']:['save','refresh','failed-refresh']){
   await page.evaluate(({seed,phase})=>{
    document.body.innerHTML='<main></main>';const root=document.querySelector('main'),state={insights_context:'account-a:car-a'};
    const race={state,writes:[],release:null,held:false};window.ledgerRace=race;
    const request=async(url,payload)=>{
     if(payload){race.writes.push(structuredClone(payload));const result={context:state.insights_context,revision:11,can_undo:true,saved_date:payload.date};if(phase==='save')return new Promise(resolve=>race.release=()=>resolve(result));return result;}
     const result={...structuredClone(seed),context:state.insights_context,revision:20};
     if(race.writes.length&&!race.held&&phase!=='save'){race.held=true;return new Promise((resolve,reject)=>race.release=()=>phase==='failed-refresh'?reject(Error('old refresh failed')):resolve(result));}
     return result;
    };
    const ui=ChargeLedgerPage.create({getState:()=>state,request,escape:s=>String(s??''),active:()=>true,time:String});
    for(const type of ['click','input','change'])document['on'+type]=e=>ui.handle(e);
    race.mount=(container=root)=>ui.mount(container);race.mount();
   },{seed,phase});
   await page.locator('[data-ledger="new"]').click();await page.locator('#ledger-amount').fill('25');await page.locator('[data-ledger="save"]').click();
   await page.waitForFunction(()=>!!ledgerRace.release);
   if(boundary!=='normal'){
    await page.evaluate(boundary=>{ledgerRace.state.insights_context=boundary==='vehicle'?'account-a:car-b':'account-b:car-a';ledgerRace.mount();if(boundary==='return-to-owner'){ledgerRace.state.insights_context='account-a:car-a';ledgerRace.mount();}},boundary);
    await page.locator('[data-ledger="new"]').click();await page.locator('#ledger-amount').fill('99');
   }
   await page.evaluate(async()=>{ledgerRace.release();await new Promise(resolve=>setTimeout(resolve,0));const old=document.querySelector('main'),fresh=old.cloneNode(false);old.replaceWith(fresh);ledgerRace.mount(fresh);});
   assert.equal(await page.evaluate(()=>ledgerRace.writes.length),1,'only one explicitly submitted bill');
   assert.equal(await page.evaluate(()=>ledgerRace.writes[0].amount),'25','old save keeps its original payload');
   if(boundary==='normal'){
    assert.match(await page.locator('main').innerText(),/账单已保存/);
    assert.equal(await page.locator('#ledger-amount').count(),0,'completed save closes old editor');
    if(phase==='failed-refresh')assert.match(await page.locator('main').innerText(),/列表尚未刷新/);
   }else{
    assert.equal(await page.locator('#ledger-amount').inputValue(),'99',boundary+' '+phase+' preserves new amount');
    assert.equal(await page.locator('[data-ledger="save"]').isEnabled(),true,'new draft stays usable');
    assert.doesNotMatch(await page.locator('main').innerText(),/账单已保存|列表尚未刷新|old refresh failed/,boundary+' '+phase+' excludes old status');
   }
  }
  assert.deepEqual(errors,[]);
  console.log('LEDGER_SAVE_CONTEXT_PASS: 11 delayed save/refresh cases across account, vehicle and returning owner');
 }finally{await page.close();}
}

(async()=>{const f=await fixture({demo:true,initialResearch:false}),{page}=f;try{
  await page.getByRole('button',{name:'用车账本',exact:true}).click();
  await page.getByRole('button',{name:'充电账本',exact:true}).click();
  await page.getByLabel('账本月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取账本',exact:true}).click();
  await page.locator('#ledger-range').waitFor();
  await page.getByRole('button',{name:'费用总览',exact:true}).click();
  assert.equal(await page.getByLabel('账本月份',{exact:true}).inputValue(),'2026-09','switching tabs keeps the selected month');
  await page.waitForFunction(()=>document.querySelector('#books-totals strong')?.textContent==='3,677.10 元');
  await page.locator('[data-books-record]').filter({hasText:'年度车险'}).waitFor();
  assert.equal(await page.locator('[data-books-record]').count(),4);
  assert.equal(await page.getByRole('button',{name:'刷新状态',exact:true}).count(),0);
  await page.getByRole('button',{name:'生活账本',exact:true}).click();
  await page.locator('#life-total').waitFor();
  assert.equal(await page.getByLabel('账本月份',{exact:true}).inputValue(),'2026-09');
  assert.equal(await page.locator('#life-start').inputValue(),'2026-09-01');
  assert.equal(await page.locator('#life-end').inputValue(),'2026-09-30');
  assert.equal(await page.locator('[data-life-expense]').count(),3);
  await page.getByRole('button',{name:'新增支出',exact:true}).click();
  await page.getByLabel('支出名称',{exact:true}).fill('跨页保留草稿');
  await page.getByRole('button',{name:'充电账本',exact:true}).click();
  await page.getByLabel('账本月份',{exact:true}).fill('2026-10');
  await page.getByRole('button',{name:'读取账本',exact:true}).click();
  await page.getByRole('button',{name:'生活账本',exact:true}).click();
  await page.locator('#life-total').waitFor();
  assert.equal(await page.getByLabel('支出名称',{exact:true}).inputValue(),'跨页保留草稿');
  await page.evaluate(()=>render());
  assert.equal(await page.getByLabel('账本月份',{exact:true}).inputValue(),'2026-10','poll repaint retains the shared picker');
  assert.equal(await page.locator('#life-start').inputValue(),'2026-10-01');
  await page.reload();await page.getByLabel('支出名称',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('账本月份',{exact:true}).inputValue(),'2026-10');
  assert.equal(await page.getByLabel('支出名称',{exact:true}).inputValue(),'跨页保留草稿');
  await page.locator('[data-detail=life-range] > summary').click();
  await page.locator('#life-start').fill('2026-08-01');
  await page.locator('#life-end').fill('2026-09-30');
  await page.getByRole('button',{name:'查询生活账本',exact:true}).click();
  await page.locator('#life-total').waitFor();
  await page.getByRole('button',{name:'充电账本',exact:true}).click();
  await page.getByRole('button',{name:'生活账本',exact:true}).click();
  assert.equal(await page.locator('#life-start').inputValue(),'2026-08-01','custom history range survives tab switching');
  assert.equal(await page.locator('#life-end').inputValue(),'2026-09-30');
  await page.getByRole('button',{name:'回到所选月份',exact:true}).click();
  await page.locator('#life-total').waitFor();
  assert.equal(await page.locator('#life-start').inputValue(),'2026-10-01','explicit month selection leaves custom range');
  await page.getByRole('button',{name:'费用总览',exact:true}).click();
  await page.getByLabel('账本月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取费用总览',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#books-totals strong')?.textContent==='3,677.10 元');
  await layouts(page,'books-compact-overview');
  await page.getByRole('button',{name:'生活账本',exact:true}).click();
  await page.getByLabel('支出名称',{exact:true}).waitFor();
  await page.getByLabel('支出日期',{exact:true}).fill('2026-09-20');
  await page.getByLabel('实际支出金额（元）',{exact:true}).fill('7');
  let releaseWrite,enteredWrite;
  const writeGate=new Promise(resolve=>releaseWrite=resolve),entered=new Promise(resolve=>enteredWrite=resolve);
  await page.route('**/api/insights/life',async route=>{if(route.request().method()==='POST'){enteredWrite();await writeGate;}await route.continue();});
  await page.getByRole('button',{name:'保存支出',exact:true}).click();await entered;
  assert.equal(await page.getByLabel('账本月份',{exact:true}).isDisabled(),true,'month cannot change during a write');
  assert.equal(await page.getByRole('button',{name:'费用总览',exact:true}).isDisabled(),true,'tabs cannot change during a write');
  await page.evaluate(()=>render());
  assert.equal(await page.getByLabel('账本月份',{exact:true}).isDisabled(),true,'poll keeps the write lock');
  releaseWrite();
  await page.waitForFunction(()=>document.querySelector('#books-totals strong')?.textContent==='3,684.10 元');
  assert.equal(await page.getByLabel('账本月份',{exact:true}).isDisabled(),false);
  const ledgerSeed=await(await page.request.get(f.origin+'/api/insights/ledger?date=2026-09-01')).json();
  await ledgerSaveRaces(f.browser,ledgerSeed);
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
  console.log('BOOKS_PERIOD_PASS: shared month, real merged records, totals, retained drafts, reload, desktop layouts and delayed calendar save/refresh context isolation');
}catch(error){await f.fail(error);throw error;}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1});
