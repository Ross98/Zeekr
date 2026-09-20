const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture({automatic:true}),{page}=f;
  try{
    let reads=0;
    page.on('request',r=>{if(r.url().endsWith('/api/insights/automatic'))reads++;});
    await page.getByRole('button',{name:'自动洞察',exact:true}).click();
    await page.locator('#auto-energy').waitFor();
    assert.match(await page.locator('#auto-status').innerText(),/最近分析已完成/);
    assert.match(await page.locator('#auto-charging').innerText(),/交流充电 · 5 次/);
    assert.match(await page.locator('#auto-charging').innerText(),/直流充电 · 5 次/);
    assert.match(await page.locator('#auto-charging').innerText(),/有效样本不足/);
    assert.match(await page.locator('#auto-quality').innerText(),/重复缓存/);
    await layouts(page,'automatic-insights');
    await page.setViewportSize({width:1440,height:1000});
    const oldTime=await page.locator('#auto-generated').innerText();
    const count=reads;
    const response=page.waitForResponse(r=>r.url().endsWith('/api/insights/automatic'));
    await page.evaluate(()=>{const original=Date.now;Date.now=()=>original()+31000;render();});
    await response;
    assert.ok(reads>count,'dashboard heartbeat refreshes saved analysis');
    await page.getByRole('button',{name:'车辆时间机',exact:true}).click();
    const inactiveReads=reads;
    await page.evaluate(()=>{const original=Date.now;Date.now=()=>original()+31000;render();});
    assert.equal(reads,inactiveReads,'inactive analysis does not poll');
    await page.getByRole('button',{name:'自动洞察',exact:true}).click();
    await page.locator('#auto-reload:not(:disabled)').waitFor();
    await page.route('**/api/insights/automatic',r=>r.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'合成读取失败'})}));
    await page.getByRole('button',{name:'读取最新结论',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'合成读取失败'}).waitFor();
    assert.equal(await page.locator('#auto-generated').innerText(),oldTime);
    await page.unroute('**/api/insights/automatic');
    const current=await page.evaluate(async()=>await (await fetch('/api/insights/automatic')).json());
    for(const status of ['stale','partial','error','changed','waiting']){
      const data={...current,status,...(['changed','waiting'].includes(status)?{report:null}:{})};
      await page.route('**/api/insights/automatic',r=>r.fulfill({contentType:'application/json',body:JSON.stringify(data)}));
      await page.getByRole('button',{name:'读取最新结论',exact:true}).click();
      await page.locator('#auto-reload:not(:disabled)').waitFor();
      if(['changed','waiting'].includes(status))assert.equal(await page.locator('#auto-energy').count(),0);
      else assert.equal(await page.locator('#auto-energy').count(),1);
      await page.unroute('**/api/insights/automatic');
    }
    let release;
    const pending=new Promise(resolve=>release=resolve);
    await page.route('**/api/insights/automatic',async r=>{await pending;await r.fulfill({contentType:'application/json',body:JSON.stringify(current)});});
    const started=page.waitForRequest(r=>r.url().endsWith('/api/insights/automatic'));
    await page.getByRole('button',{name:'读取最新结论',exact:true}).click();await started;
    await page.evaluate(()=>{state={...state,insights_context:''};render();});
    const finished=page.waitForResponse(r=>r.url().endsWith('/api/insights/automatic'));
    release();await finished;
    assert.match(await page.locator('#auto-status').innerText(),/等待当前车辆缓存/);
    assert.equal(await page.locator('#auto-energy').count(),0,'late old-account results discarded');
    assert.deepEqual(f.posts,[]);assert.deepEqual(f.external,[]);assert.deepEqual(f.errors,[]);
    console.log('UI_AUTOMATIC_INSIGHTS_PASS: saved analysis, sufficient/insufficient samples, background refresh, inactive pause, stale/partial/error/changed/empty states, failure preservation, account race, day/night/mobile/zoom/contrast; no cloud or writes');
  }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
