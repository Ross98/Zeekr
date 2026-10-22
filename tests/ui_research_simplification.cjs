const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{const f=await fixture({demo:true,automatic:true}),{page}=f;try{
 await page.clock.setFixedTime(new Date('2026-09-20T08:00:00Z'));
 await page.reload();await page.getByRole('button',{name:'用车研究',exact:true}).click();
 await page.locator('#field-results [data-review-path]').first().waitFor();
 assert.equal(await page.locator('[data-insight-view]').count(),1,'Only parameter research remains in research navigation');
 assert.equal(await page.locator('[data-review-focus="pending"]').getAttribute('aria-pressed'),'true');
 let reads=0;page.on('request',r=>{if(r.url().includes('/api/insights/research?'))reads++;});
 await page.evaluate(()=>render());assert.equal(reads,0,'Rendering does not trigger archive analysis');
 await page.getByRole('button',{name:'分析近 7 天',exact:true}).click();
 await page.locator('#parameter-study-status').filter({hasText:'截至'}).waitFor({timeout:30000});
 assert.equal(await page.locator('[data-review-focus="changed"]').getAttribute('aria-pressed'),'true');
 await page.locator('#field-results [data-review-path]').first().click();
 await page.locator('#parameter-changes').filter({hasText:'变化发生在两次观测之间'}).waitFor({timeout:30000});
 assert.ok(await page.locator('#parameter-changes article').count()>0);
 assert.equal(await page.locator('#parameter-flow [data-parameter-advanced]').getAttribute('aria-expanded'),'false');
 await layouts(page,'research-simplified');
 // A result from the previous account cannot repopulate the focused directory.
 let release,started;const gate=new Promise(resolve=>release=resolve),requestStarted=new Promise(resolve=>started=resolve);
 await page.route('**/api/insights/research?*',async route=>{started();await gate;await route.continue();});
 await page.getByRole('button',{name:'分析近 7 天',exact:true}).click();await requestStarted;
 await page.evaluate(()=>{state={...state,insights_context:'different-research-owner'};render();});
 const finished=page.waitForResponse(r=>r.url().includes('/api/insights/research?'));release();const response=await finished;await response.finished();
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 await page.waitForFunction(()=>reviewStudy===null);
 assert.equal(await page.locator('[data-review-focus="changed"]').isDisabled(),true);
 await page.unroute('**/api/insights/research?*');await page.reload();

 await page.getByRole('button',{name:'用车周报',exact:true}).click();
 await page.locator('#report-date').fill('2026-09-20');await page.getByRole('button',{name:'查看报告',exact:true}).click();
 await page.locator('#report-title').waitFor();
 await page.getByRole('button',{name:'读取本周地点',exact:true}).click();await page.locator('#report-places').filter({hasText:'参考地点'}).waitFor();
 assert.equal(await page.locator('#report-automatic details > summary').innerText(),'近期能耗趋势');
 await page.locator('#report-automatic details > summary').click();await page.getByRole('button',{name:'读取最新结论',exact:true}).click();await page.locator('#auto-generated').waitFor();
 assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);assert.ok(f.posts.every(url=>{const target=new URL(url);return target.origin===f.origin&&/^\/api\/analysis\/[a-f0-9]{32}\/cancel$/.test(target.pathname)&&url===f.origin+target.pathname;}),JSON.stringify(f.posts));console.log('UI_RESEARCH_SIMPLIFICATION_PASS');
}catch(error){await f.fail(error);throw error;}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
