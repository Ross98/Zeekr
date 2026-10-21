const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
// Catches counting null metrics as zero, duplicate tags, local-time buckets and name-only route merges.
const scope={window:{}};vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../zeekr_control/static/trip-tags.js'),'utf8'),scope);
assert.equal(typeof scope.window.TripTagsPage.tagAnalysis,'function','tag analysis must derive real event metrics');
const records=[
{id:'a',tags:['通勤','接送'],end_time:Date.parse('2026-09-08T09:00:00+08:00'),start_time:Date.parse('2026-09-08T08:00:00+08:00'),distance_km:20,duration_seconds:3600,start_place:'home',end_place:'work',partial:false},
{id:'b',tags:['通勤','通勤'],end_time:Date.parse('2026-09-09T01:00:00+08:00'),start_time:Date.parse('2026-09-09T00:30:00+08:00'),distance_km:null,duration_seconds:1800,start_place:'work',end_place:'home',partial:true},
{id:'c',tags:['出游'],end_time:Date.parse('2026-09-12T11:00:00+08:00'),start_time:null,distance_km:0,duration_seconds:null,start_place:null,end_place:null,partial:false}
];
const a=scope.window.TripTagsPage.tagAnalysis(records,'通勤',[{id:'home',label:'家'},{id:'work',label:'公司'}],'2026-09',Date.parse('2026-10-21T00:00:00+08:00'));
assert.equal(a.count,2);assert.equal(a.share,2/3);assert.equal(a.distance.total,20);assert.equal(a.distance.samples,1);assert.equal(a.distance.mean,20);assert.equal(a.duration.total,5400);assert.equal(a.duration.mean,2700);assert.equal(a.partial,1);assert.equal(a.only,1);assert.equal(a.overlap[0].tag,'接送');assert.equal(a.overlap[0].count,1);assert.equal(a.hours[0].count,1);assert.equal(a.hours[1].count,1);assert.equal(a.weekdays,2);assert.equal(a.routes.length,1);assert.equal(a.routes[0].count,2);assert.equal(a.weeks[0].count,0);assert.equal(a.weeks[1].count,2);
const empty=scope.window.TripTagsPage.tagAnalysis(records,'不存在',[],'2026-09');assert.equal(empty.distance.total,null);assert.equal(empty.duration.mean,null);
async function batchOwnerIsolation(browser,seed){
 const p=await browser.newPage({viewport:{width:1440,height:1000}});try{
 await p.addScriptTag({path:require('node:path').join(__dirname,'../zeekr_control/static/trip-tags.js')});
 for(const scenario of ['switch','return']){
 await p.evaluate(({seed,scenario})=>{document.body.innerHTML='<main></main>';let state={insights_context:'old-owner'};const race={state,release:null,writes:0};const data={...structuredClone(seed),events:[{...seed.events[0],id:'race-a',tags:['原标签'],manual_tags:['原标签'],note:'原备注'},{...seed.events[0],id:'race-b',tags:[],manual_tags:[],note:''}]};const request=async(url,payload)=>{if(url.includes('commute-rule'))return{context:state.insights_context,commute_rule:seed.commute_rule};if(payload){race.writes++;return new Promise(resolve=>race.release=()=>resolve({context:'old-owner',revision:123,can_undo:true}));}return{...structuredClone(data),context:state.insights_context};};const ui=TripTagsPage.create({getState:()=>state,request,escape:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),active:()=>true,time:String});// Returning false from a DOM on* callback cancels native checkbox activation.
for(const type of ['input','change','click'])document['on'+type]=e=>{ui.handle(e);};race.mount=()=>ui.mount(document.querySelector('main'));window.race=race;race.mount();},{seed,scenario});
 await p.locator('[data-tag="load"]').click();await p.locator('[data-tag="load"]:not(:disabled)').waitFor();await p.locator('#tag-check-all').click();assert.equal(await p.locator('#tag-check-all').isChecked(),true);await p.locator('#tag-batch-label').fill('旧批量标签');await p.locator('[data-tag="batch-add"]').click();await p.waitForFunction(()=>!!race.release);
 await p.evaluate(scenario=>{race.state.insights_context='new-owner';race.mount();if(scenario==='return'){race.state.insights_context='old-owner';race.mount();}},scenario);
 await p.locator('[data-tag="load"]').click();await p.locator('[data-tag="load"]:not(:disabled)').waitFor();await p.locator('[data-tag-event="race-a"] [data-tag="edit"]').click();await p.locator('#tag-labels').fill('新草稿');await p.evaluate(async()=>{race.release();await new Promise(resolve=>setTimeout(resolve,0));});assert.equal(await p.locator('#tag-labels').inputValue(),'新草稿',scenario+' retains new context draft');assert.equal(await p.evaluate(()=>race.writes),1,scenario+' never submits the next old-context row');
 }
 }finally{await p.close();}
}

async function batchIntegration(){
 const f=await fixture({initialResearch:false}),{page}=f;
 page.setDefaultTimeout(10000);
 try{
  await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();await page.getByRole('button',{name:'行程标签',exact:true}).click();await page.getByLabel('标签月份',{exact:true}).fill('2026-09');await page.getByRole('button',{name:'读取行程标签',exact:true}).click();await page.locator('[data-tag-event]').first().waitFor();
  await page.locator('[data-tag-event="report-trip"] [data-tag="edit"]').click();await page.getByLabel('行程标签（逗号分隔）',{exact:true}).fill('原有标签');await page.getByLabel('行程备注',{exact:true}).fill('必须保留的备注');await page.getByRole('button',{name:'保存行程标签',exact:true}).click();await page.locator('#tag-tools-panel').waitFor({state:'hidden'});
  await page.locator('[data-tag-check="report-trip"]').check();await page.locator('[data-tag-check="report-partial"]').check();await page.getByLabel('批量添加标签',{exact:true}).fill('接送');await page.getByRole('button',{name:'批量添加',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[data-tag-event="report-partial"]')?.textContent.includes('接送'));
  await page.locator('[data-tag-event="report-trip"] [data-tag="edit"]').click();assert.equal(await page.getByLabel('行程备注',{exact:true}).inputValue(),'必须保留的备注');assert.match(await page.getByLabel('行程标签（逗号分隔）',{exact:true}).inputValue(),/原有标签.*接送/);await page.getByRole('button',{name:'取消标注',exact:true}).click();
  let writes=0;await page.route('**/api/insights/trip-tags',async route=>{if(route.request().method()!=='POST')return route.continue();writes++;if(writes===2)return route.fulfill({status:409,json:{error:'synthetic revision conflict'}});return route.continue();});
  await page.locator('#tag-check-all').check();await page.getByLabel('批量添加标签',{exact:true}).fill('途中办事');await page.getByRole('button',{name:'批量添加',exact:true}).click();await page.locator('[data-tag="load"]:not(:disabled)').waitFor();
  assert.match(await page.locator('#trip-tags-workspace [role="alert"]:visible').innerText(),/已完成 1 \/ 3 趟/,'Partial batch failure must remain visible after refreshing actual persisted rows');assert.equal(writes,2,'Conflict stops the rest of the batch');
  assert.equal(await page.locator('[data-tag-event]').filter({hasText:'途中办事'}).count(),1,'Only acknowledged saves are persisted');
  assert.deepEqual(f.errors,[]);
 }finally{await f.close();}
}

(async()=>{const f=await fixture({initialResearch:false}),{page}=f;try{
 page.setDefaultTimeout(10000);
 await page.route('**/api/insights/trip-tags?*',async route=>{const res=await route.fetch(),d=await res.json(),seed=d.events[0];d.events=Array.from({length:30},(_,i)=>({...seed,id:'visual-'+i,tags:i<20?(i<4?['通勤','接送']:['通勤']):[],manual_tags:i<20?(i<4?['通勤','接送']:['通勤']):[],note:i===0?'保留备注':''}));await route.fulfill({json:d});});
 await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();await page.getByRole('button',{name:'行程标签',exact:true}).click();await page.getByLabel('标签月份',{exact:true}).fill('2026-09');await page.getByRole('button',{name:'读取行程标签',exact:true}).click();await page.locator('[data-tag-event]').first().waitFor();
 await page.locator('[data-tag="analysis-select"][data-id="通勤"]').click();
 assert.equal(await page.locator('[data-tag-analysis-title]').innerText(),'通勤分析');
 const pair=page.locator('.tag-work-grid');const baseline=await pair.evaluate(e=>[...e.children].map(c=>c.getBoundingClientRect().height));assert.ok(Math.abs(baseline[0]-baseline[1])<1);
 assert.ok(await page.locator('.tag-event-list').evaluate(e=>e.scrollHeight>e.clientHeight));
 await page.locator('.tag-event-list').evaluate(e=>e.scrollTop=e.scrollHeight);assert.ok(await page.locator('[data-tag-event="visual-19"]').isVisible());
 await page.locator('[data-tag="overlap-select"][data-id="接送"]').click();assert.equal(await page.locator('[data-tag-event]').count(),4);
 const after=await pair.evaluate(e=>[...e.children].map(c=>c.getBoundingClientRect().height));assert.deepEqual(after,baseline,'Filtering must not resize either card');
 await page.locator('[data-tag="overlap-select"][data-id="alone"]').click();assert.equal(await page.locator('[data-tag-event]').count(),16);
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);for(const width of [1440,1280,1024]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'desktop overflow');}}
 fs.mkdirSync('/tmp/zeekr-insights-qa',{recursive:true});await page.screenshot({path:'/tmp/zeekr-insights-qa/trip-tags-visual-desktop.png',fullPage:true});await batchIntegration();await contrast(page,'#trip-tags-workspace');await batchOwnerIsolation(f.browser,await page.evaluate(async()=>{const r=await fetch('/api/insights/trip-tags?date=2026-09-01');return r.json();}));assert.deepEqual(f.errors,[]);console.log('UI_TRIP_TAGS_VISUAL_PASS: real metrics, tag switch, overlap, fixed cards, scrolling, batch persistence/conflict/owner isolation, desktop themes/contrast');
}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
