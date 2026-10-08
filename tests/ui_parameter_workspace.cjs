// Synthetic desktop workflow; all records belong to the disposable fixture.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture(),{page}=f;
  page.setDefaultTimeout(8000);
  try{
    assert.equal(await page.locator('[data-insight-group="2"] [data-insight-view]').count(),1,'One parameter workspace replaces the three tool entries');
    await page.getByRole('button',{name:'参数研究与核实',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('[data-review-path]').length===217);
    const path='additionalVehicleStatus.electricVehicleStatus.chargeLevel';
    await page.locator('#search').fill(path);
    await page.locator('[data-review-path]').click();
    assert.equal(await page.locator('#review-panel').getAttribute('data-path'),path);
    assert.equal(await page.locator('.hypothesis-catalog').count(),0,'Analysis uses the shared field list');
    await page.getByRole('button',{name:'2 分析证据',exact:true}).click();
    await page.locator('#hypothesis-start').fill('2026-09-20');
    await page.locator('#hypothesis-end').fill('2026-09-20');
    await page.getByRole('button',{name:'分析所选参数',exact:true}).click();
    await page.getByRole('button',{name:'采用假设写结论',exact:true}).waitFor();
    assert.equal(await page.locator('#review-panel').getAttribute('data-path'),path,'Full analysis must not switch the selected parameter');
    assert.match(await page.locator('.hypothesis-evidence').innerText(),/chargeLevel/);
    await page.getByRole('button',{name:'采用假设写结论',exact:true}).click();
    await page.locator('#review-meaning').fill('合成 SOC 假设');
    await page.locator('#review-observation').fill('合成证据，待核实');
    await page.getByRole('button',{name:'保存',exact:true}).click();
    await page.waitForFunction(()=>state.field_reviews.records.some(r=>r.meaning==='合成 SOC 假设'));
    await page.getByRole('button',{name:'3 操作验证',exact:true}).click();
    await page.getByRole('button',{name:'新建实验',exact:true}).click();
    for(const side of ['前','后']){
      await page.getByLabel(`${side}样本日期`,{exact:true}).fill('2026-09-20');
      await page.getByRole('button',{name:`读取${side}样本`,exact:true}).click();
    }
    await page.getByLabel('前样本',{exact:true}).selectOption({index:1});
    await page.getByLabel('后样本',{exact:true}).selectOption({index:2});
    await page.getByRole('button',{name:'比较实验样本',exact:true}).click();
    await page.locator('[data-lab-field]').waitFor();
    assert.equal(await page.locator('[data-lab-field]').count(),1,'Field experiments default to the selected parameter');
    await page.getByLabel('实验名称',{exact:true}).fill('合成 SOC 实验');
    await page.getByLabel('实际动作',{exact:true}).fill('手动记录，未操作车辆');
    await page.getByLabel('动作时间（北京时间）',{exact:true}).fill('2026-09-20T00:00:30');
    await page.getByRole('button',{name:'保存实验记录',exact:true}).click();
    await page.locator('[data-lab-record]').waitFor();
    assert.equal(await page.getByRole('button',{name:'用前样本写结论',exact:true}).count(),1,'Saved experiments offer a direct next step to write the conclusion');
    await page.getByRole('button',{name:'用前样本写结论',exact:true}).click();
    await page.getByText(/已关联实验：合成 SOC 实验/).waitFor();
    assert.equal(await page.locator('#review-panel').getAttribute('data-path'),path);
    assert.equal(await page.locator('[data-insight-view="parameters"]').getAttribute('aria-pressed'),'true');
    await page.getByLabel('确认含义',{exact:true}).fill('合成 SOC 人工核实');
    await page.getByRole('button',{name:'保存',exact:true}).click();
    await page.waitForFunction(()=>state.field_reviews.records.some(r=>r.evidence?.title==='合成 SOC 实验'));
    const records=await page.evaluate(()=>state.field_reviews.records);
    assert.ok(records.some(r=>r.path===path&&r.evidence?.title==='合成 SOC 实验'));
    await page.getByLabel('核实范围',{exact:true}).selectOption('field');
    await page.getByLabel('核实结果',{exact:true}).selectOption('confirmed');
    await page.getByRole('button',{name:'保存',exact:true}).click();
    await page.waitForFunction(()=>state.field_reviews.records.some(r=>r.scope==='field'&&r.status==='confirmed'));
    await page.getByRole('button',{name:'2 分析证据',exact:true}).click();
    assert.equal(await page.getByRole('button',{name:'采用假设写结论',exact:true}).isDisabled(),true,'Manual confirmation immediately protects the hypothesis editor');
    await page.getByRole('button',{name:'4 写结论',exact:true}).click();
    await page.locator('#search').fill('chargeLevel');
    await page.locator(`[data-review-path="${path}"]`).click();
    await page.getByRole('button',{name:'暂时跳过',exact:true}).click();
    assert.equal(await page.locator('#review-panel').getAttribute('data-path'),path,'Next-item navigation skips parameters without usable values');
    await page.locator('#search').fill(path);await page.locator('[data-review-path]').click();
    await page.locator('#review-observation').fill('未保存结论草稿');
    await page.getByRole('button',{name:'3 操作验证',exact:true}).click();
    await page.getByRole('button',{name:'回看实验',exact:true}).click();
    await page.getByLabel('研究备注',{exact:true}).fill('未保存实验草稿');
    // Missing fields stay searchable, and cannot be confirmed using a missing raw value.
    await page.locator('#search').fill('');
    const missing=await page.evaluate(()=>reviewVisibleFields().find(f=>f.research_only).path);
    await page.locator('#search').fill(missing);
    await page.locator('[data-review-path]').click();
    assert.equal(await page.getByRole('button',{name:'4 写结论',exact:true}).isDisabled(),true);
    assert.match(await page.locator('#lab-draft-owner').innerText(),/chargeLevel/,'Switching fields must keep the draft associated with its original parameter');
    await page.getByRole('button',{name:'2 分析证据',exact:true}).click();
    assert.match(await page.locator('#parameter-hypotheses').innerText(),new RegExp(missing.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
    await page.locator('#search').fill(path);await page.locator('[data-review-path]').click();
    await page.getByRole('button',{name:'4 写结论',exact:true}).click();
    assert.equal(await page.locator('#review-observation').inputValue(),'未保存结论草稿');
    await page.getByRole('button',{name:'3 操作验证',exact:true}).click();
    assert.equal(await page.getByLabel('研究备注',{exact:true}).inputValue(),'未保存实验草稿');
    for(const theme of ['light','dark']){
      await page.getByLabel('外观',{exact:true}).selectOption(theme);
      for(const width of [1440,1280,1024]){
        await page.setViewportSize({width,height:1050});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width} overflow`);
        await contrast(page);
        fs.mkdirSync('/tmp/zeekr-parameter-workspace-qa',{recursive:true});
        await page.screenshot({path:`/tmp/zeekr-parameter-workspace-qa/${theme}-${width}.png`,fullPage:true});
      }
    }
    await page.evaluate(()=>{state.insights_context='other-vehicle';render();});
    assert.equal(await page.locator('[data-hypothesis=conclude]').count(),0,'Vehicle switch clears previous evidence');
    assert.equal(await page.locator('[data-lab-record]').count(),0,'Vehicle switch clears previous experiments');
    for(const legacy of ['fields','hypotheses','lab']){
      await page.goto(`${f.origin}/?p=insights&t=${legacy}`);
      await page.waitForFunction(()=>document.querySelectorAll('[data-review-path]').length===217);
      assert.equal(await page.locator('[data-insight-view="parameters"]').getAttribute('aria-pressed'),'true');
      if(legacy!=='fields')assert.equal(await page.locator(legacy==='lab'?'#parameter-experiments':'#parameter-hypotheses').isVisible(),true);
      assert.equal(new URL(page.url()).searchParams.get('t'),'parameters');
    }
    await page.goto(`${f.origin}/?p=fields`);
    await page.locator('[data-insight-view="parameters"][aria-pressed="true"]').waitFor({state:'attached'});
    await page.getByRole('heading',{name:'参数研究与核实',exact:true}).waitFor();
    assert.equal(new URL(page.url()).searchParams.get('p'),'insights');
    let releaseCatalog,catalogStarted;
    const catalogGate=new Promise(resolve=>releaseCatalog=resolve),catalogRequest=new Promise(resolve=>catalogStarted=resolve);
    await page.route('**/api/vehicle/parameters',async route=>{catalogStarted();await catalogGate;await route.continue();});
    await page.goto(`${f.origin}/?p=insights&t=fields`);await catalogRequest;
    await page.evaluate(path=>selectReviewField(path),missing);
    releaseCatalog();
    await page.waitForFunction(()=>reviewCatalog.length===217);
    assert.equal(await page.locator('#review-panel').getAttribute('data-path'),missing,'Opening a historical field before its catalog arrives keeps that selection');
    await page.unroute('**/api/vehicle/parameters');
    await page.setViewportSize({width:1440,height:1050});
    await page.locator('#search').fill(path);await page.locator('[data-review-path]').click();
    await page.evaluate(()=>{scrollTo(0,0);document.activeElement?.blur();});
    await page.screenshot({path:'/tmp/zeekr-parameter-workspace-qa/overview.png',fullPage:true});
    assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
    console.log('DESKTOP_PARAMETER_WORKSPACE_PASS shared selection, full catalog, hypothesis, experiment evidence, guarded review, missing fields, context reset, six layouts');
  }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
