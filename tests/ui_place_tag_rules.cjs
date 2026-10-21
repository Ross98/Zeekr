const assert=require('node:assert/strict'),fs=require('node:fs');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
async function ruleContextRaces(browser,seed){
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 try{
  for(const file of ['place-tag-rules.js','trip-tags.js'])await page.addScriptTag({path:require('node:path').join(__dirname,'../zeekr_control/static',file)});
  for(const scenario of ['background','account','return','month']){
   await page.evaluate(seed=>{
    document.body.innerHTML='<main></main>';const state={insights_context:'owner-a',trip_records_revision:1,place_tag_rules_revision:[1,1]},race={state,release:null};
    const request=async(url,payload)=>{
     if(url.includes('commute-rule'))return{context:state.insights_context,commute_rule:seed.commute_rule};
     if(payload)return new Promise(resolve=>race.release=()=>resolve({context:'owner-a',token:'old-preview',counts:{add:0,remove:0,unchanged:0,excluded:0,pending:0},rows:[]}));
     return{...structuredClone(seed),context:state.insights_context};
    };
    const ui=TripTagsPage.create({getState:()=>state,request,active:()=>true,time:String,escape:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))});
    for(const type of ['input','change','click'])document['on'+type]=e=>{ui.handle(e);};race.mount=()=>ui.mount(document.querySelector('main'));window.race=race;race.mount();
   },seed);
   await page.locator('[data-tag=load]').click();await page.locator('[data-tag=load]:not(:disabled)').waitFor();await page.locator('[data-tag=places-panel-open]').click();await page.locator('[data-tag=places-panel-tab][data-id=auto]').click();
   await page.getByLabel('绑定地点',{exact:true}).selectOption('rule_test_station');await page.getByLabel('自动添加的行程标签',{exact:true}).fill('旧草稿');await page.getByRole('button',{name:'预览匹配',exact:true}).click();await page.waitForFunction(()=>!!race.release);
   if(scenario==='background'){
    await page.evaluate(async()=>{race.release();await new Promise(r=>setTimeout(r,0));});assert.equal(await page.locator('[data-tag=place-rule-save]').isEnabled(),true);
    await page.evaluate(()=>{race.state.place_tag_rules_revision=[2,2];race.mount();});assert.equal(await page.getByLabel('自动添加的行程标签',{exact:true}).inputValue(),'旧草稿');assert.equal(await page.locator('[data-tag=place-rule-save]').isDisabled(),true);
   }else{
    await page.evaluate(scenario=>{race.state.insights_context='owner-b';race.mount();if(scenario==='return'){race.state.insights_context='owner-a';race.mount();}},scenario);
    await page.locator('[data-tag=load]').click();await page.locator('[data-tag=load]:not(:disabled)').waitFor();await page.locator('[data-tag=places-panel-open]').click();await page.locator('[data-tag=places-panel-tab][data-id=auto]').click();await page.getByLabel('自动添加的行程标签',{exact:true}).fill('新草稿');
    await page.evaluate(async()=>{race.release();await new Promise(r=>setTimeout(r,0));});assert.equal(await page.getByLabel('自动添加的行程标签',{exact:true}).inputValue(),'新草稿');assert.equal(await page.locator('[data-tag=place-rule-save]').isDisabled(),true);
    if(scenario==='month'){await page.getByRole('button',{name:'关闭地点面板',exact:true}).click();await page.getByLabel('标签月份',{exact:true}).fill('2026-11');assert.equal(await page.locator('[data-tag=place-rule-save]').count(),0);}
   }
  }
 }finally{await page.close();}
}
(async()=>{const f=await fixture({initialResearch:false,placeTagRules:true}),{page}=f;try{
 page.setDefaultTimeout(10000);
 await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();await page.getByRole('button',{name:'行程标签',exact:true}).click();await page.getByLabel('标签月份',{exact:true}).fill('2026-09');await page.getByRole('button',{name:'读取行程标签',exact:true}).click();await page.locator('[data-tag-event="rules-arrival"]').waitFor();
 await page.getByRole('button',{name:'查看与管理地点',exact:true}).click();await page.getByRole('button',{name:'自动标注规则',exact:true}).click();
 await page.getByLabel('绑定地点',{exact:true}).selectOption('rule_test_station');await page.getByLabel('自动添加的行程标签',{exact:true}).fill('充电');await page.getByLabel('还需匹配充电记录',{exact:true}).check();
 assert.equal(await page.getByRole('button',{name:'保存标注规则',exact:true}).isDisabled(),true);
 await page.getByRole('button',{name:'预览匹配',exact:true}).click();await page.locator('[data-place-rule-result="rules-arrival"]').waitFor();assert.match(await page.locator('[data-place-rule-result="rules-arrival"]').innerText(),/新增/);assert.match(await page.locator('[data-place-rule-result="rules-pending"]').innerText(),/待补充/);
 await page.getByLabel('自动添加的行程标签',{exact:true}).fill('临时草稿');
 assert.equal(await page.getByRole('button',{name:'保存标注规则',exact:true}).isDisabled(),true);
 await page.evaluate(()=>render());assert.equal(await page.getByLabel('自动添加的行程标签',{exact:true}).inputValue(),'临时草稿');
 await page.getByLabel('自动添加的行程标签',{exact:true}).fill('充电');await page.getByRole('button',{name:'预览匹配',exact:true}).click();await page.getByRole('button',{name:'保存标注规则',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#tag-place-panel')?.textContent.includes('已保存，默认用于后续行程'));
 await page.getByRole('button',{name:'关闭地点面板',exact:true}).click();assert.doesNotMatch(await page.locator('[data-tag-event="rules-arrival"] .tag-record-meta').innerText(),/充电/,'Saving must not rewrite old trips');
 await page.getByRole('button',{name:'查看与管理地点',exact:true}).click();await page.getByRole('button',{name:'自动标注规则',exact:true}).click();await page.getByRole('button',{name:'预览本月历史匹配',exact:true}).click();await page.getByRole('button',{name:'应用本月历史匹配',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#tag-place-panel')?.textContent.includes('历史匹配已应用'));
 await page.getByRole('button',{name:'关闭地点面板',exact:true}).click();assert.match(await page.locator('[data-tag-event="rules-arrival"] .tag-record-meta').innerText(),/充电/);assert.doesNotMatch(await page.locator('[data-tag-event="rules-pending"] .tag-record-meta').innerText(),/充电/);
 await page.locator('[data-tag-event="rules-arrival"] [data-tag=edit]').click();await page.getByRole('button',{name:'排除本趟地点规则标签',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#tag-tools-panel')?.textContent.includes('已排除本趟'));
 await page.getByRole('button',{name:'关闭工具面板',exact:true}).click();assert.doesNotMatch(await page.locator('[data-tag-event="rules-arrival"] .tag-record-meta').innerText(),/充电/);
 await page.getByRole('button',{name:'查看与管理地点',exact:true}).click();await page.getByRole('button',{name:'自动标注规则',exact:true}).click();await page.getByRole('button',{name:'预览本月历史匹配',exact:true}).click();assert.match(await page.locator('[data-place-rule-result="rules-arrival"]').innerText(),/手动排除/);
 for(const theme of['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);for(const width of[1440,1280,1024]){await page.setViewportSize({width,height:1000});const box=await page.locator('#tag-place-panel').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}await contrast(page,'#tag-place-panel');}
 await page.setViewportSize({width:1440,height:1000});await page.locator('.place-rule-card').first().evaluate(el=>el.scrollTop=0);
 fs.mkdirSync('/tmp/zeekr-insights-qa',{recursive:true});await page.locator('#tag-place-panel').screenshot({path:'/tmp/zeekr-insights-qa/place-tag-rules-desktop.png'});assert.deepEqual(f.errors,[]);const seed=await page.evaluate(async()=>await(await fetch('/api/insights/trip-tags?date=2026-09-01')).json());await ruleContextRaces(f.browser,seed);console.log('UI_PLACE_TAG_RULES_PASS: draft preview, future-only save, explicit historical apply, exclusion, themes/contrast');
}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1});
