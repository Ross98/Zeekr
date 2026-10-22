const assert=require('node:assert/strict');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
async function sharedTheme(page){
 const mismatches=await page.evaluate(()=>{
  const probe=document.createElement('span');document.body.append(probe);
  const checks=[['#charging-review','backgroundColor','--bg'],['#charging-review','color','--ink'],
   ['.cr-analysis','backgroundColor','--paper'],['.cr-analysis','borderTopColor','--line'],
   ['#charging-review .cr-muted','color','--muted'],['.cr-added','backgroundColor','--accent'],
   ['.cr-share-ac','backgroundColor','--chart-ac'],['.cr-share-dc','backgroundColor','--chart-dc'],
   ['.cr-share-unknown','backgroundColor','--chart-unknown']];
  const errors=[];
  for(const [selector,property,token] of checks){const node=document.querySelector(selector);if(!node)continue;
   probe.style.color='var('+token+')';const expected=getComputedStyle(probe).color,actual=getComputedStyle(node)[property];
   if(actual!==expected)errors.push({selector,property,expected,actual});
  }
  probe.remove();return errors;
 });
 assert.deepEqual(mismatches,[],'charging review follows shared theme colors');
 await contrast(page,'#charging-review');
}
(async()=>{const requests=[];const f=await fixture({demo:true,initialResearch:false,beforeGoto:async p=>p.on('request',r=>requests.push(new URL(r.url()).pathname))}),{page}=f;try{
 await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
 await page.getByLabel('充电月份',{exact:true}).waitFor();
 assert.equal(await page.locator('.energy-top').count(),0);assert.equal(await page.getByRole('button',{name:'充电曲线对比',exact:true}).count(),0);
 await page.getByLabel('充电月份',{exact:true}).fill('2026-09');
 await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2026-09');
 assert.ok(await page.locator('[data-review-record]').count());
 assert.equal(await page.getByRole('heading',{name:'充电花费构成',exact:true}).count(),1);
 const driving=page.locator('.cr-analysis-metrics>div').nth(2);
 assert.match(await driving.innerText(),/区间依据不足，暂无法估算/);
 assert.equal(await driving.locator('strong').innerText(),'样本不足');
 const values=await page.locator('.cr-total>strong').evaluateAll(nodes=>nodes.map(n=>getComputedStyle(n).fontSize));assert.equal(new Set(values).size,1);
 await page.locator('[data-review-expand]').first().click();
 assert.match(await page.locator('.cr-detail').innerText(),/电表|地点|费用/);
 assert.equal(requests.filter(p=>p==='/api/charging/process').length,0,'review does not read the current process');
 await page.getByRole('button',{name:'查看充电曲线',exact:true}).first().click();
 await page.getByRole('heading',{name:'充电详情',exact:true}).waitFor();
 await page.getByRole('tab',{name:'充电回顾',exact:true}).click();await page.getByLabel('充电月份',{exact:true}).waitFor();
 assert.equal(await page.getByLabel('充电月份',{exact:true}).inputValue(),'2026-09');
 await page.reload();await page.getByLabel('充电月份',{exact:true}).waitFor();assert.equal(await page.getByLabel('充电月份',{exact:true}).inputValue(),'2026-09');
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);await sharedTheme(page);for(const width of [1024,1280,1440]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}}
 await page.getByLabel('充电月份',{exact:true}).fill('2024-02');await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2024-02');assert.equal(await page.locator('[data-review-record]').count(),0);
 let held,seen=0;
 const delayed=async route=>{seen++;if(seen===1)await new Promise(resolve=>{held=resolve;});await route.fallback();};
 await page.route('**/api/insights/charging-review?date=2025-01-01',delayed);
 const firstRead=page.waitForRequest('**/api/insights/charging-review?date=2025-01-01');
 await page.getByLabel('充电月份',{exact:true}).fill('2025-01');await page.getByLabel('充电月份',{exact:true}).blur();
 await firstRead;
 await page.getByRole('button',{name:'车辆',exact:true}).first().click();
 await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
 await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2025-01',{},{timeout:5000});
 held();await page.unroute('**/api/insights/charging-review?date=2025-01-01',delayed);
 assert.ok(seen>=2,'returning after a cancelled first read retries automatically');
 await page.evaluate(async()=>{
   let saved=await fetch('/api/insights/ledger?date=2026-07-01').then(r=>r.json()),revision=saved.revision;
   for(const [i,event_id] of ['curve-a','curve-b','curve-gap'].entries()){
     const r=await fetch('/api/insights/ledger',{method:'POST',headers:{'Content-Type':'application/json','X-Request-Key':state.request_key},body:JSON.stringify({context:state.insights_context,action:'save',revision,event_id,date:'2026-07-'+(12+i),source:'unknown',amount:['100','0.01','5'][i],metered_kwh:'40'})});
     const body=await r.json();if(!r.ok)throw Error(body.error);revision=body.revision;
   }
 });
 await page.getByLabel('充电月份',{exact:true}).fill('2026-07');await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2026-07');
 assert.equal(await page.locator('[data-cost-mode=ac]').count(),1);assert.equal(await page.locator('[data-cost-mode=dc]').count(),1);
 assert.match(await page.locator('.cr-total').first().innerText(),/105.01/);
 assert.deepEqual(await page.locator('.cr-kwh strong').allTextContents(),['40','40','40']);
 assert.deepEqual(await page.locator('.cr-kwh small').allTextContents(),['kWh · 账单电量','kWh · 账单电量','kWh · 账单电量']);
 assert.match(await page.locator('.cr-total').nth(1).innerText(),/累计充电量/);
 assert.match(await page.locator('.cr-total').nth(1).innerText(),/120/);
 assert.match(await page.locator('.cr-total').nth(1).innerText(),/3 次账单/);
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);await sharedTheme(page);for(const width of [1024,1280,1440]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));const labels=await page.locator('.cr-share-label').evaluateAll(ns=>ns.map(n=>n.getBoundingClientRect().toJSON()));assert.ok(labels[0].right<=labels[1].left);}}
 await page.locator('[data-review-expand]').first().click();await page.getByRole('button',{name:'打开账单',exact:true}).click();
 await page.getByLabel('实际账单金额（元）',{exact:true}).waitFor();
 assert.equal(await page.getByLabel('关联充电记录',{exact:true}).inputValue(),'curve-gap');
 await page.getByRole('button',{name:'返回来源页面',exact:true}).click();await page.getByLabel('充电月份',{exact:true}).waitFor();assert.equal(await page.getByLabel('充电月份',{exact:true}).inputValue(),'2026-07');
 assert.deepEqual(f.errors,[]);console.log('CHARGING_REVIEW_BROWSER_PASS: monthly real saved APIs; no current state; equal numbers; curves; URL/month; empty months; desktop themes');
}catch(error){await f.fail(error);throw error;}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
