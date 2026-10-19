// Desktop status diagram: synthetic snapshot pinned across background polling.
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 let snapshot;
 const f=await fixture({evidenceTestId:'ui_status_summary',initialResearch:false,beforeGoto:async page=>{
  await page.route('**/api/state',async route=>{const response=await route.fetch();await route.fulfill({response,json:snapshot||await response.json()});});
 }}),{page}=f;
 try{
  await page.getByRole('button',{name:'刷新状态',exact:true}).click();
  await page.waitForFunction(()=>state?.model&&!busy&&!polling);
  snapshot=await page.evaluate(()=>{
   const s=structuredClone(state);s.profile.image='/car.svg';
   s.model.doors=['右前','右后','左前','左后'].map(name=>({name,door:'关闭',window:'关闭',lock:'已锁'}));
   s.model.doors[1].window='未知';s.model.doors[1].lock='未知';s.model.doors[3].door='打开';
   s.model.doors[0].lock='未锁';
   s.model.hood='关闭';s.model.trunk='关闭';s.model.lock={confirmed:false,value:'未知'};
   s.model.updated_time=Date.now()-20*60000;s.model.temperature_updated_time=Date.now()-2*3600000;
   s.model.metrics.inside='25.6°C';s.model.metrics.outside='23.1°C';
   s.model.fields=s.model.fields.filter(f=>f.key!=='interiorPM25').concat({key:'interiorPM25',group:'空气质量',value:8});return s;
  });
  await page.evaluate(s=>{state=s;render();},snapshot);
  assert.equal(await page.locator('.overview-part').count(),7,'four doors, hood, trunk and central lock');
  assert.equal(await page.locator('.overview-vehicle').count(),1,'one consolidated vehicle state card');
  assert.match(await page.locator('.overview-status-counts').innerText(),/需关注 2 项.*未知 3 项.*15 项/s);
  assert.match(await page.locator('.overview-pm25').innerText(),/PM2.5.*8.*单位待核实/s);
  assert.equal(await page.locator('.overview-pm25 strong').innerText(),'8','show the concentration exactly, never its level code');
  assert.match(await page.locator('.overview-cabin').innerText(),/独立更新时间未提供/);
  assert.match(await page.locator('.hero .freshness').innerText(),/车辆数据更新于.*20 分钟前.*不代表实时状态/s);
  assert.match(await page.locator('.overview-cabin').innerText(),/温度更新于.*2 小时/);
  assert.doesNotMatch(await page.locator('.overview-tyre-readings').innerText(),/25\.6°C|23\.1°C/,'cabin temperature cannot masquerade as tyre temperature');
  assert.doesNotMatch(await page.locator('.overview-vehicle').innerText(),/additionalVehicleStatus|sunroofPos|原始值|全部正常/);
  assert.doesNotMatch(await page.locator('.overview-pm25').innerText(),/µg|μg|ppm|温度更新/);
  const photo=page.locator('.overview-vehicle-stage .car-tyre-art img');
  await photo.evaluate(image=>image.decode());
  assert.equal(await photo.evaluate(image=>image.complete&&image.naturalWidth>0),true,'official local photo actually decodes');
  assert.match(await photo.getAttribute('src'),/^\/car-top-.*\.webp$/);
  assert.equal(await page.locator('.car-tyre-art svg').count(),0,'parameter icons do not replace the model photo');
  assert.equal(await page.locator('.overview-part-lr.state-attention').count(),1);
  assert.equal(await page.locator('.overview-part-rr.state-unknown').count(),1);
  assert.equal(await page.locator('.overview-part-hood.state-safe').count(),1);
  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   for(const width of [1024,1280,1440,1920]){
    await page.setViewportSize({width,height:1100});
    await page.evaluate(()=>scrollTo(0,0));
    const counts=await page.locator('.overview-status-counts').boundingBox();
    assert.ok(counts.y+counts.height<=1100,'state counts fit the first desktop screen');
    const bad=await page.locator('.overview-vehicle-stage').evaluate(el=>{
     const art=el.querySelector('.car-tyre-art').getBoundingClientRect(),box=el.getBoundingClientRect();
     return [...el.querySelectorAll('.overview-part')].filter(e=>{const r=e.getBoundingClientRect();return !r.width||r.left<box.left-1||r.right>box.right+1||(r.left<art.right&&r.right>art.left&&r.top<art.bottom&&r.bottom>art.top);}).map(e=>e.dataset.overviewPart);
    });assert.deepEqual(bad,[],`${theme} ${width} diagram bounds`);
    const [rf,rr,lf,lr]=await Promise.all(['rf','rr','lf','lr'].map(key=>page.locator('.overview-part-'+key).boundingBox()));
    assert.ok(rf.x+rf.width<=rr.x&&lf.x+lf.width<=lr.x&&rf.y<lf.y&&rr.y<lr.y,'door positions follow the left-facing car');
    const signatures=await page.locator('.overview-part-hood,.overview-part-rr,.overview-part-lr').evaluateAll(nodes=>nodes.map(node=>{const s=getComputedStyle(node);return [s.color,s.borderStyle,s.backgroundColor].join('|');}));
    assert.equal(new Set(signatures).size,3,`${theme} safe/attention/unknown remain visually distinct`);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   }
  }
  await page.locator('[data-overview-status="attention"]').click();
  assert.match(await page.locator('[data-status-list="attention"]').innerText(),/右前门锁.*未锁.*左后车门.*打开/s);
  assert.equal(await page.locator('[data-status-list="attention"] button').count(),2);
  await page.locator('[data-overview-status="unknown"]').click();
  assert.equal(await page.locator('.overview-status-list:not([hidden]) button').count(),3);
  async function pollSnapshot(){
   await page.waitForFunction(()=>!polling&&!busy);
   const before=await page.evaluate(()=>generation);
   snapshot.read_time++;
   await page.evaluate(async()=>{await pollState(true);});
   await page.waitForFunction(expected=>state.read_time===expected&&!polling,snapshot.read_time);
   assert.ok(await page.evaluate(()=>generation)>before,'state polling actually redraws the overview');
  }
  await pollSnapshot();
  assert.equal(await page.locator('[data-overview-status="unknown"]').getAttribute('aria-expanded'),'true','polling preserves expanded unknown list');
  assert.equal(await page.locator('[data-status-list="unknown"]').isVisible(),true);
  await page.locator('[data-overview-status="attention"]').click();
  await pollSnapshot();
  assert.equal(await page.locator('[data-overview-status="attention"]').getAttribute('aria-expanded'),'true','polling preserves expanded attention list');
  assert.equal(await page.locator('[data-status-list="attention"]').isVisible(),true);
  assert.equal(await page.locator('[data-status-list="unknown"]').isVisible(),false,'only the selected list stays open');
  await page.locator('[data-overview-status="attention"]').click();
  await pollSnapshot();
  assert.equal(await page.locator('[data-overview-status="attention"]').getAttribute('aria-expanded'),'false','polling preserves manual collapse');
  assert.equal(await page.locator('.overview-status-list:not([hidden])').count(),0);
  await page.locator('[data-overview-status="unknown"]').click();
  await page.locator('.overview-status-list [data-overview-part="rr"]').first().click();
  assert.match(await page.locator('#overview-part-detail').innerText(),/右后门.*门锁 未知.*车窗 未知/s);
  await page.locator('#overview-part-detail [data-overview-parameters]').click();
  await page.locator('.vehicle-table').waitFor();
  assert.equal(await page.locator('#vehicle-group').inputValue(),'门窗与安全');
  assert.equal(await page.locator('#vehicle-search').inputValue(),'右后');
  assert.equal(await page.locator('#vehicle-status').inputValue(),'all');
  assert.equal(await page.getByRole('button',{name:'状态总览',exact:true}).count(),0);
  await page.getByLabel('搜索参数',{exact:true}).fill('nothing');
  await page.locator('#vehicle-status').selectOption('missing');
  await page.getByRole('button',{name:'总览',exact:true}).first().click();
  await page.locator('.overview-vehicle [data-overview-tool="parameters"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-parameter]').length===217);
  assert.equal(await page.locator('#vehicle-search').inputValue(),'');assert.equal(await page.locator('#vehicle-group').inputValue(),'all');assert.equal(await page.locator('#vehicle-status').inputValue(),'all');
  await page.getByRole('button',{name:'总览',exact:true}).first().click();
  await page.locator('.overview-pm25').click();await page.locator('.vehicle-table').waitFor();
  assert.ok(await page.locator('[data-parameter]').count()>0);assert.ok((await page.locator('[data-parameter]').evaluateAll(rows=>rows.map(r=>r.dataset.parameter))).every(path=>path.includes('interiorPM25')));
  await page.getByRole('button',{name:'总览',exact:true}).first().click();
  for(const value of [0,'0',null,'',-1,'bad']){
   await page.evaluate(value=>{state.model.fields.find(f=>f.key==='interiorPM25').value=value;render();},value);
   assert.match(await page.locator('.overview-pm25').innerText(),value===0||value==='0'?/PM2.5.*0/s:/暂无数据/);
  }
  await page.evaluate(()=>{state.model.fields=state.model.fields.filter(f=>f.key!=='interiorPM25');render();});
  assert.match(await page.locator('.overview-pm25').innerText(),/暂无数据/,'absent concentration cannot become zero or a level code');
  for(const change of [{request_key:'another-service'},{insights_context:'another-account'},{vehicle:'another-vehicle'}]){
   if(await page.locator('[data-overview-status="unknown"]').getAttribute('aria-expanded')!=='true')await page.locator('[data-overview-status="unknown"]').click();
   snapshot={...snapshot,...change};await pollSnapshot();
   assert.equal(await page.locator('.overview-status-list:not([hidden])').count(),0,'owner change clears expansion: '+Object.keys(change)[0]);
   assert.equal(await page.locator('[data-overview-status="unknown"]').getAttribute('aria-expanded'),'false');
  }
  await page.evaluate(()=>{state.vehicle='another';state.model.doors.forEach(d=>{d.door='关闭';d.window='关闭';d.lock='已锁';});state.model.lock={confirmed:true,value:'已锁'};render();});
  assert.match(await page.locator('.overview-status-counts').innerText(),/需关注 0 项.*未知 0 项/s);
  assert.equal(await page.locator('.overview-part-rf').getAttribute('aria-pressed'),'true');
  assert.equal(await page.locator('.overview-status-list button').count(),0,'vehicle switch clears previous issues');
  snapshot=await page.evaluate(()=>{
   state.model.updated_time=null;state.model.updated_at='未知';
   state.model.temperature_updated_time=null;state.model.temperature_updated_at='未知';
   state.model.doors.forEach(d=>{d.door='未知';d.window='未知';d.lock='未知';});
   state.model.doors[0].door='未核实值';state.model.hood=state.model.trunk='未知';
   state.model.lock={confirmed:false,value:'未知'};render();return structuredClone(state);
  });
  assert.match(await page.locator('.hero .freshness').innerText(),/更新时间未知/);
  assert.match(await page.locator('.overview-cabin').innerText(),/更新时间未知/);
  assert.match(await page.locator('.overview-status-counts').innerText(),/需关注 0 项.*未知 15 项/s);
  assert.equal(await page.locator('.overview-part.state-safe').count(),0);
  assert.equal(await page.locator('.overview-part.state-unknown').count(),7);
  await page.locator('[data-overview-status="unknown"]').click();
  assert.equal(await page.locator('[data-status-list="unknown"] button').count(),15);
  assert.match(await page.locator('[data-status-list="unknown"]').innerText(),/未核实值/,'unexpected labels remain visible and unknown');
  const retained=await page.locator('.overview-vehicle').innerText();
  await page.route('**/api/refresh',route=>route.fulfill({status:502,json:{error:'合成刷新失败'}}));
  await page.getByRole('button',{name:'刷新状态',exact:true}).click();
  await page.getByText(/合成刷新失败/).first().waitFor();
  assert.equal(await page.locator('.overview-vehicle').innerText(),retained,'failed refresh retains all prior state, uncertainty and source times');
  assert.match(await page.locator('.hero .freshness').innerText(),/更新时间未知/);
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
  console.log('DESKTOP_STATUS_SUMMARY_PASS: 15 states/all unknown, official photo decode, independent freshness, semantic colors/positions, PM2.5 zero/missing, contextual/reset navigation, polling/owner isolation, failed refresh retention, 8 desktop layouts');
 }catch(error){await f.fail(error);throw error;}finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
