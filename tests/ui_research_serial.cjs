const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{const f=await fixture({demo:true}),{page}=f;const gates=[],requests=[];let overviews=0;try{
 await page.clock.setFixedTime(new Date('2026-09-20T08:00:00Z'));await page.reload();await page.getByRole('button',{name:'用车研究',exact:true}).click();
 await page.locator('#field-results [data-review-path]').first().waitFor();
 await page.route('**/api/insights/research?*',async route=>{
  const path=new URL(route.request().url()).searchParams.get('path');if(!path){overviews++;return route.continue();}
  requests.push(path);await new Promise(resolve=>gates.push(resolve));await route.continue();
 });
 await page.getByRole('button',{name:'分析近 7 天',exact:true}).click();await page.locator('#parameter-study-status').filter({hasText:'截至'}).waitFor();
 await page.waitForFunction(()=>document.querySelector('#parameter-changes')?.textContent.includes('正在读取'));
 await page.waitForTimeout(100);assert.equal(requests.length,1);
 const paths=await page.locator('[data-review-path]').evaluateAll(rows=>rows.slice(0,3).map(row=>row.dataset.reviewPath));assert.equal(paths.length,3);
 await page.evaluate(paths=>{for(const path of [paths[1],paths[2],paths[1],paths[2]])document.querySelector(`[data-review-path="${path}"]`).click();},paths);
 await page.waitForTimeout(150);assert.equal(requests.length,1,'Rapid parameter selection must not dispatch concurrent scans');
 const lastStarted=page.waitForRequest(r=>new URL(r.url()).searchParams.get('path')===paths[2]);gates.shift()();await lastStarted;await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));assert.deepEqual(requests,[paths[0],paths[2]],'Only the final selection follows the running scan');
 assert.match(await page.locator('#parameter-changes').innerText(),/正在读取/,'Discarded response cannot populate the selected parameter');
 gates.shift()();await page.locator('#parameter-changes').filter({hasText:'变化发生在两次观测之间'}).waitFor();
 await page.locator(`[data-review-path="${paths[1]}"]`).click();await page.waitForTimeout(100);assert.equal(requests.length,3);
 await page.locator(`[data-review-path="${paths[2]}"]`).click();await page.getByRole('button',{name:'总览',exact:true}).click();
 gates.shift()();await page.waitForTimeout(150);assert.equal(requests.length,3,'Leaving clears the queued selection');
 const resumed=page.waitForRequest(r=>new URL(r.url()).searchParams.get('path')===paths[2]);await page.getByRole('button',{name:'用车研究',exact:true}).click();await resumed;await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));assert.equal(requests.length,4,'Returning can read the selected field again');assert.equal(requests[3],paths[2]);
 gates.shift()();await page.locator('#parameter-changes').filter({hasText:'变化发生在两次观测之间'}).waitFor();
 // A new overview also waits for a running field read; field choices cannot replace it.
 await page.locator(`[data-review-path="${paths[1]}"]`).click();await page.waitForTimeout(100);
 const fieldCount=requests.length;await page.getByRole('button',{name:'分析近 7 天',exact:true}).click();
 await page.evaluate(paths=>{for(const path of [paths[1],paths[2]])document.querySelector(`[data-review-path="${path}"]`).click();},paths);
 await page.waitForTimeout(150);assert.equal(overviews,1,'Overview shares the same serial lane');assert.equal(requests.length,fieldCount);
 const overviewStarted=page.waitForRequest(r=>r.url().includes('/api/insights/research?')&&!new URL(r.url()).searchParams.get('path'));
 const finalStarted=page.waitForRequest(r=>new URL(r.url()).searchParams.get('path')===paths[2]);gates.shift()();await overviewStarted;await finalStarted;
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));assert.equal(overviews,2);assert.equal(requests.length,fieldCount+1);assert.equal(requests.at(-1),paths[2]);
 gates.shift()();await page.locator('#parameter-changes').filter({hasText:'变化发生在两次观测之间'}).waitFor();
 assert.deepEqual(f.errors,[]);console.log('UI_RESEARCH_SERIAL_PASS: single in-flight read, latest selection, stale result exclusion, leave and return');
}finally{gates.forEach(release=>release());await f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
