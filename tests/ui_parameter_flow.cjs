// Real disposable API and synthetic archive: exercise the user's ordered workflow.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {fixture,contrast,parameterStage}=require('./ui_insight_helpers.cjs');
async function reviewSaveRaces(page,path){
  const original=await page.evaluate(()=>{window.reviewRaceOriginalApi=api;return {context:state.insights_context,vehicle:state.field_reviews.vehicle};});
  try{
    for(const boundary of ['account','vehicle','return-to-owner','normal'])for(const phase of boundary==='normal'?['save','conflict-refresh','failed-refresh']:['save','failed-save','conflict-refresh','failed-refresh']){
      await page.evaluate(({original,path,phase})=>{
        const catalog=[...reviewCatalog];
        state.insights_context=original.context;state.field_reviews={vehicle:original.vehicle,revision:10,records:[]};reviewSync();
        setReviewCatalog(catalog);selectReviewField(path);editReviewStep(true);
        const race={phase,catalog,writes:[],oldRelease:null,newRelease:null,holdState:false};window.reviewRace=race;
        api=async(url,payload)=>{
          if(url==='/api/field-reviews'){
            race.writes.push(structuredClone(payload));
            if(race.writes.length===1){
              race.oldVehicle=payload.vehicle;race.oldContext=payload.context;
              if(!['save','failed-save'].includes(phase)){race.holdState=true;throw Error('old save conflict');}
              return new Promise((resolve,reject)=>race.oldRelease=()=>phase==='failed-save'?reject(Error('old save failed')):resolve({vehicle:payload.vehicle,revision:11,records:[payload]}));
            }
            return new Promise(resolve=>race.newRelease=()=>resolve({vehicle:payload.vehicle,revision:21,records:[payload]}));
          }
          if(url==='/api/state'){
            if(race.holdState){race.holdState=false;return new Promise((resolve,reject)=>race.oldRelease=()=>phase==='failed-refresh'?reject(Error('old refresh failed')):resolve({insights_context:race.oldContext,field_reviews:{vehicle:race.oldVehicle,revision:11,records:[]}}));}
            return structuredClone(state);
          }
          return reviewRaceOriginalApi(url,payload);
        };
      },{original,path,phase});
      await page.locator('#review-meaning').fill('旧结论');await page.locator('#review-note').evaluate(el=>el.closest('details').open=true);await page.locator('#review-note').fill('旧备注');
      await page.getByRole('button',{name:'保存',exact:true}).click();
      await page.waitForFunction(()=>!!reviewRace.oldRelease);
      if(boundary==='normal'){
        await page.evaluate(async()=>{reviewRace.oldRelease();await new Promise(resolve=>setTimeout(resolve,0));});
        assert.equal(await page.evaluate(()=>reviewSaving),false,'same-context completion unlocks its editor');
        assert.equal(await page.evaluate(()=>state.field_reviews.revision),phase==='failed-refresh'?10:11);
        if(phase==='save'){assert.equal(await page.evaluate(()=>state.field_reviews.records[0].meaning),'旧结论');assert.equal(await page.evaluate(()=>state.field_reviews.records[0].note),'旧备注');}
        else{assert.equal(await page.evaluate(()=>reviewDraft().meaning),'旧结论');assert.equal(await page.evaluate(()=>reviewDraft().note),'旧备注');}
        if(phase!=='save')assert.match(await page.locator('#review-error').innerText(),/old save conflict/);
        assert.equal(await page.evaluate(()=>reviewRace.writes.length),1);continue;
      }
      await page.evaluate(({original,path,boundary})=>{
        const switchTo=(context,vehicle)=>{state.insights_context=context;state.field_reviews={vehicle,revision:20,records:[]};reviewSync();setReviewCatalog(reviewRace.catalog);selectReviewField(path);editReviewStep(true);};
        switchTo('synthetic-new-context',boundary==='vehicle'?'synthetic-new-car':original.vehicle);
        if(boundary==='return-to-owner')switchTo(original.context,original.vehicle);
      },{original,path,boundary});
      assert.equal(await page.locator('#review-meaning').isEnabled(),true,boundary+' enables new context editor while old operation waits');
      await page.locator('#review-meaning').fill('新结论');await page.locator('#review-note').evaluate(el=>el.closest('details').open=true);await page.locator('#review-note').fill('新备注');
      const owner=await page.evaluate(()=>({context:state.insights_context,vehicle:state.field_reviews.vehicle}));
      await page.getByRole('button',{name:'保存',exact:true}).click();await page.waitForFunction(()=>!!reviewRace.newRelease);
      await page.evaluate(async()=>{reviewRace.oldRelease();await new Promise(resolve=>setTimeout(resolve,0));renderReviewPanel();});
      assert.equal(await page.locator('#review-meaning').inputValue(),'新结论',boundary+' '+phase+' preserves new conclusion');
      assert.equal(await page.locator('#review-note').inputValue(),'新备注',boundary+' '+phase+' preserves new note');
      assert.equal(await page.locator('#review-meaning').isDisabled(),true,'old finally must not unlock the newer pending save');
      assert.deepEqual(await page.evaluate(()=>({context:state.insights_context,vehicle:state.field_reviews.vehicle,revision:state.field_reviews.revision})),{...owner,revision:20});
      assert.equal(await page.evaluate(()=>reviewDraft().dirty),true,'new pending draft remains dirty');
      assert.equal(await page.evaluate(()=>reviewUndo),null,'old completion cannot create undo in the new context');
      assert.equal(await page.evaluate(()=>reviewRace.writes.length),2,'exactly the two explicit saves');
      assert.doesNotMatch(await page.locator('#review-error').innerText(),/old save conflict|old save failed|old refresh failed/);
      await page.evaluate(async()=>{reviewRace.newRelease();await new Promise(resolve=>setTimeout(resolve,0));});
      assert.equal(await page.evaluate(()=>reviewSaving),false);
      assert.equal(await page.evaluate(()=>state.field_reviews.revision),21);
      assert.equal(await page.evaluate(()=>state.field_reviews.records[0].meaning),'新结论');
    }
    console.log('FIELD_REVIEW_SAVE_CONTEXT_PASS: 15 strict delayed save/conflict cases, account/vehicle/return, new drafts and newer write lock');
  }finally{await page.evaluate(()=>{api=reviewRaceOriginalApi;delete window.reviewRaceOriginalApi;});}
}

(async()=>{const f=await fixture(),{page}=f;page.setDefaultTimeout(10000);try{
  await page.getByRole('button',{name:'全部参数',exact:true}).click();
  await page.waitForFunction(()=>reviewCatalog.length===217);
  assert.equal(await page.locator('#parameter-flow [data-parameter-advanced]').getAttribute('aria-expanded'),'false','Advanced study starts collapsed');
  assert.deepEqual(await page.locator('#parameter-flow [data-parameter-step]:visible').allTextContents(),['看变化','写结论']);
  assert.equal(await page.locator('[data-review-path][aria-pressed=true]').isVisible(),true);
  assert.ok(await page.locator('[data-review-path][aria-pressed=true]').evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}),'The selected field is visible next to its detail');
  const path='additionalVehicleStatus.electricVehicleStatus.chargeLevel';
  await page.locator('#search').fill(path);await page.locator('[data-review-path]').click();
  await parameterStage(page,'evidence');
  assert.equal(await page.locator('#review-panel').getAttribute('data-path'),path);
  assert.equal(await page.locator('#hypothesis-text').count(),0,'No unrelated default parking hypothesis');
  await page.locator('#hypothesis-start').fill('2026-09-20');await page.locator('#hypothesis-end').fill('2026-09-20');
  await page.getByRole('button',{name:'分析所选参数',exact:true}).click();
  await page.getByRole('button',{name:'采用假设写结论',exact:true}).waitFor();
  assert.equal(await page.locator('.hypothesis-notebook textarea').count(),0,'Evidence and conclusion use one editor');
  assert.equal(await page.locator('.hypothesis-evidence table').isVisible(),false,'Raw distribution is available on demand');
  await page.getByRole('button',{name:'采用假设写结论',exact:true}).click();
  assert.equal(await page.locator('[data-parameter-step=conclusion]').getAttribute('aria-current'),'step');
  assert.equal(await page.locator('#review-status').inputValue(),'question');
  await page.getByLabel('确认含义',{exact:true}).fill('SOC 工作流假设');
  await page.getByLabel('实际观察',{exact:true}).fill('支持与反例仍需复核');
  await parameterStage(page,'evidence');
  assert.equal(new URL(page.url()).searchParams.get('step'),'evidence');
  await page.goBack();
  await page.locator('[data-parameter-step=conclusion][aria-current=step]').waitFor();
  assert.equal(await page.getByLabel('确认含义',{exact:true}).inputValue(),'SOC 工作流假设','Browser back returns to the step and draft');
  await parameterStage(page,'evidence');
  await parameterStage(page,'conclusion');
  assert.equal(await page.getByLabel('确认含义',{exact:true}).inputValue(),'SOC 工作流假设','Returning to the conclusion preserves the draft');
  await page.getByRole('button',{name:'保存',exact:true}).click();
  await page.waitForFunction(()=>state.field_reviews.records.some(r=>r.meaning==='SOC 工作流假设'));
  assert.equal(await page.evaluate(()=>state.field_reviews.records.find(r=>r.meaning==='SOC 工作流假设').status),'question');
  await parameterStage(page,'experiment');
  assert.equal(await page.locator('#lab-form').isVisible(),false,'Reading associated experiments does not begin a new experiment');
  await page.getByRole('button',{name:'新建实验',exact:true}).click();
  await page.getByLabel('实验名称',{exact:true}).fill('SOC 操作验证');
  await page.getByLabel('实际动作',{exact:true}).fill('记录用户实际动作');
  await page.locator('#search').fill('additionalVehicleStatus.electricVehicleStatus.chargeSts');
  await page.locator('[data-review-path]').click();
  assert.equal(await page.locator('[data-parameter-step=experiment]').getAttribute('aria-current'),'step');
  assert.match(await page.locator('#lab-draft-owner').innerText(),/chargeLevel/,'An unfinished operation retains the field chosen when it began');
  await page.locator('#search').fill(path);await page.locator('[data-review-path]').click();
  await parameterStage(page,'evidence');
  await parameterStage(page,'experiment');
  assert.equal(await page.getByLabel('实验名称',{exact:true}).inputValue(),'SOC 操作验证');
  // A detailed history visit has an explicit return to the originating field and step.
  await parameterStage(page,'evidence');
  await page.getByRole('button',{name:'完整历史、分布与场景',exact:true}).click();
  await page.getByRole('button',{name:'返回参数研究',exact:true}).waitFor();
  await page.getByRole('button',{name:'返回参数研究',exact:true}).click();
  assert.equal(await page.locator('#review-panel').getAttribute('data-path'),path);
  assert.equal(await page.locator('[data-parameter-step=evidence]').getAttribute('aria-current'),'step');
  assert.equal(await page.locator('#search').inputValue(),path);
  assert.equal(await page.locator('[data-review-path]').count(),1,'Returning from history retains the list filter');
  await parameterStage(page,'experiment');
  assert.equal(await page.getByLabel('实验名称',{exact:true}).inputValue(),'SOC 操作验证');
  for(const theme of ['light','dark']){
    await page.getByLabel('外观',{exact:true}).selectOption(theme);
    for(const width of [1440,1280,1024]){
      await page.setViewportSize({width,height:1050});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width} overflow`);
      await contrast(page);
    }
  }
  await page.setViewportSize({width:1440,height:1050});
  await parameterStage(page,'evidence');
  fs.mkdirSync('/tmp/zeekr-parameter-flow-qa',{recursive:true});
  await page.evaluate(()=>{document.activeElement?.blur();document.querySelector('#toast').hidden=true;scrollTo({top:0,behavior:'instant'});});
  await page.screenshot({path:'/tmp/zeekr-parameter-flow-qa/evidence.png',fullPage:true});
  await parameterStage(page,'overview');
  await page.evaluate(()=>{document.activeElement?.blur();scrollTo({top:0,behavior:'instant'});});
  await page.screenshot({path:'/tmp/zeekr-parameter-flow-qa/overview.png',fullPage:true});
  await reviewSaveRaces(page,path);
  await page.evaluate(()=>{state.insights_context='other-car';render();});
  assert.equal(await page.locator('#review-form').count(),0);
  assert.equal(await page.locator('#lab-title').isVisible(),false);
  assert.equal(await page.locator('#lab-title').inputValue(),'');
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
  console.log('DESKTOP_PARAMETER_FLOW_PASS ordered steps, shared conclusion, drafts, experiment entry, history return, context isolation, delayed saves/conflict refreshes across account/vehicle/return, six layouts');
}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
