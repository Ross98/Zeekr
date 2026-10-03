// Synthetic local state only. No vehicle requests or notification retries.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture(),{page}=f;
  try{
    const original=await page.evaluate(()=>structuredClone(state));
    const healthy={...original,authenticated:true,error:null,
      recording:{...original.recording,active:true,status:'active',error:''},
      monitoring:{online:true,status:'fresh',error:'',events:[],trip:'idle',charge:'idle'},
      model:{...original.model,updated_time:Date.now()}};
    let response=healthy;
    await page.route('**/api/state',r=>r.fulfill({json:response}));
    async function show(patch={}){
      response={...structuredClone(healthy),...patch};
      await page.evaluate(value=>{state=value;page='overview';sectionTask='';render();},response);
    }
    await show();
    assert.equal(await page.locator('#overview-attention').isVisible(),false,'healthy summary occupies no space');
    await show({model:{...healthy.model,updated_time:Date.now()-7200000},read_time:Date.now()});
    await page.getByRole('button',{name:/车况已 2 小时.*未更新/}).waitFor({timeout:1500});
    assert.match(await page.locator('#overview-attention').innerText(),/缓存提示/);
    await page.getByRole('button',{name:/车况已/}).click();
    assert.equal(await page.locator('#main').getAttribute('data-page'),'settings');
    await page.getByLabel('质量分析开始日期',{exact:true}).waitFor();
    await show({model:{...healthy.model,updated_time:null}});
    assert.match(await page.locator('#overview-attention').innerText(),/车辆更新时间未知/);
    await show({model:{...healthy.model,updated_time:Date.now()+120000}});
    assert.match(await page.locator('#overview-attention').innerText(),/车辆时间超前/);
    // The local clock must also reveal ageing without a new snapshot revision.
    await show({model:{...healthy.model,updated_time:Date.now()-181000}});
    assert.match(await page.locator('#overview-attention').innerText(),/3 分钟未更新/);
    await show({model:{...healthy.model,updated_time:Date.now()-179000}});
    assert.equal(await page.locator('#overview-attention').isVisible(),false);
    await page.waitForFunction(()=>!document.querySelector('#overview-attention').hidden,{},{timeout:4000});
    await show({monitoring:{...healthy.monitoring,status:'blocked',error:'认证状态异常，请检查车辆连接。',events:[
      {kind:'trip_end',delivery:'failed',alert_delivery:'failed'},
      {kind:'charge_end',delivery:'uncertain',alert_delivery:'sent'},
      {kind:'charge_start',delivery:'failed',alert_delivery:'sent'},
      {kind:'trip_end',delivery:'pending',alert_delivery:'sending'},
      {kind:'charge_end',delivery:'historical',alert_delivery:'cancelled'}]}});
    assert.match(await page.locator('#overview-attention').innerText(),/账号认证异常.*最近 1 条通知失败.*1 条发送结果待确认/s);
    assert.equal(await page.locator('#overview-attention [data-attention-target]').first().innerText(),'账号认证异常');
    await page.getByRole('button',{name:'查看处理',exact:true}).click();
    assert.equal(await page.locator('#main').getAttribute('data-page'),'settings');
    assert.equal(await page.evaluate(()=>document.activeElement?.id),'settings-account-title');
    assert.match(await page.locator('#settings-account').innerText(),/认证异常/);
    await show({error:'读取状态失败；请重新登录。'});
    assert.match(await page.locator('#overview-attention').innerText(),/账号连接需要检查/);
    await show({error:'本地轨迹存储暂不可用。'});
    assert.match(await page.locator('#overview-attention').innerText(),/车辆读取需要检查/);
    assert.doesNotMatch(await page.locator('#overview-attention').innerText(),/账号认证异常/);
    await show({monitoring:{...healthy.monitoring,events:[{kind:'trip_end',delivery:'failed',alert_delivery:'sent'}]}});
    await page.getByRole('button',{name:'最近 1 条通知失败',exact:true}).click();
    assert.equal(await page.locator('[data-detail="settings-notifications"]').getAttribute('open'),'');
    assert.match(await page.locator('[data-detail="settings-notifications"]').innerText(),/发送失败/);
    await show({monitoring:{...healthy.monitoring,online:false},recording:{...healthy.recording,status:'offline'}});
    assert.match(await page.locator('#overview-attention').innerText(),/后台未在线/);
    await show({monitoring:{...healthy.monitoring,status:'unavailable',online:false}});
    assert.match(await page.locator('#overview-attention').innerText(),/采集状态暂不可用/);
    await show({recording:{...healthy.recording,active:false,status:'paused'}});
    assert.match(await page.locator('#overview-attention').innerText(),/采集已暂停/);
    await show({monitoring:{...healthy.monitoring,status:'blocked',error:'采集后台异常，请检查服务状态。'}});
    assert.match(await page.locator('#overview-attention').innerText(),/采集需要处理/);
    await show({monitoring:{...healthy.monitoring,status:'retrying'}});
    assert.match(await page.locator('#overview-attention').innerText(),/状态提示.*采集连接重试中/s);
    await show({authenticated:false,model:null});
    assert.match(await page.locator('#overview-attention').innerText(),/车辆账号未连接/);
    await show({monitoring:{...healthy.monitoring,status:'cooldown',events:[{kind:'charge_end',delivery:'failed',alert_delivery:'failed'}]},model:{...healthy.model,updated_time:Date.now()-7200000}});
    fs.mkdirSync('/tmp/zeekr-attention-qa',{recursive:true});
    for(const theme of ['light','dark']){
      await page.getByLabel('外观',{exact:true}).selectOption(theme);
      for(const width of [1440,390,320]){
        await page.setViewportSize({width,height:900});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${theme} ${width} fits`);
        await contrast(page,'#overview-attention');
        if(width!==320)await page.screenshot({path:`/tmp/zeekr-attention-qa/${theme}-${width}.png`,fullPage:true});
      }
    }
    await show();
    assert.equal(await page.locator('#overview-attention').isVisible(),false,'resolved issues disappear');
    assert.deepEqual(f.posts,[]);assert.deepEqual(f.external,[]);assert.deepEqual(f.errors,[]);
    console.log('UI_OVERVIEW_ATTENTION_PASS: health, freshness, unknown/future time, auth, monitoring, notification deduplication, recovery links, themes/mobile');
  }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
