// Desktop status diagram: synthetic snapshot pinned across background polling.
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 let snapshot;
 const f=await fixture({initialResearch:false,beforeGoto:async page=>{
  await page.route('**/api/state',async route=>{const response=await route.fetch();await route.fulfill({response,json:snapshot||await response.json()});});
 }}),{page}=f;
 try{
  await page.getByRole('button',{name:'刷新状态',exact:true}).click();
  await page.waitForFunction(()=>state?.model&&!busy&&!polling);
  snapshot=await page.evaluate(()=>{
   const s=structuredClone(state);s.profile.image='/car.svg';
   s.model.doors=['右前','右后','左前','左后'].map(name=>({name,door:'关闭',window:'关闭',lock:'已锁'}));
   s.model.doors[1].window='未知';s.model.doors[1].lock='未知';s.model.doors[3].door='打开';
   s.model.hood='关闭';s.model.trunk='关闭';s.model.lock={confirmed:false,value:'未知'};
   s.model.fields=s.model.fields.filter(f=>f.key!=='interiorPM25').concat({key:'interiorPM25',group:'空气质量',value:8});return s;
  });
  await page.evaluate(s=>{state=s;render();},snapshot);
  assert.equal(await page.locator('.overview-part').count(),7,'four doors, hood, trunk and central lock');
  assert.match(await page.locator('.overview-status-counts').innerText(),/需关注 1 项.*未知 3 项.*15 项/s);
  assert.match(await page.locator('.overview-pm25').innerText(),/PM2.5.*8.*单位待核实/s);
  assert.match(await page.locator('.overview-cabin').innerText(),/独立更新时间未提供/);
  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   for(const width of [1024,1280,1440,1920]){
    await page.setViewportSize({width,height:1100});
    const bad=await page.locator('.overview-vehicle-stage').evaluate(el=>{
     const art=el.querySelector('.car-tyre-art').getBoundingClientRect(),box=el.getBoundingClientRect();
     return [...el.querySelectorAll('.overview-part')].filter(e=>{const r=e.getBoundingClientRect();return !r.width||r.left<box.left-1||r.right>box.right+1||(r.left<art.right&&r.right>art.left&&r.top<art.bottom&&r.bottom>art.top);}).map(e=>e.dataset.overviewPart);
    });assert.deepEqual(bad,[],`${theme} ${width} diagram bounds`);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   }
  }
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
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
  console.log('DESKTOP_STATUS_SUMMARY_PASS: 15 states, 7 diagram targets, PM2.5 zero/missing, contextual/reset navigation, vehicle switch, polling expansion/collapse and owner isolation, 8 desktop layouts');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
