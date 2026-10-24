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
  assert.match(await page.locator('.overview-status-counts').innerText(),/需关注 2 项.*未知 3 项/s);
  assert.match(await page.locator('.overview-pm25').innerText(),/PM2.5.*8.*μg\/m³/s);
  assert.equal(await page.locator('.overview-pm25 strong').innerText(),'8','show the concentration exactly, never its level code');
  assert.equal(await page.locator('#overview-part-detail').isVisible(),false,'details are hidden until a related target is clicked');
  assert.deepEqual(await page.locator('.overview-environment-values>button .overview-reading-label').allTextContents(),['车外','车内','PM2.5']);
  await page.locator('.overview-pm25').click();
  assert.match(await page.locator('#overview-part-detail').innerText(),/独立更新时间未提供/);
  await page.keyboard.press('Escape');
  assert.match(await page.locator('.hero .freshness').innerText(),/车辆数据更新于.*20 分钟前.*不代表实时状态/s);
  await page.locator('[data-overview-reading=inside]').click();
  assert.match(await page.locator('#overview-part-detail').innerText(),/温度更新于.*2 小时/);
  await page.locator('[data-overview-detail-close]').click();
  assert.equal(await page.locator('#overview-part-detail').isVisible(),false);
  await page.locator('[data-overview-reading=inside]').click();
  await page.locator('#overview-part-detail [data-overview-parameters]').click();
  await page.locator('.vehicle-table').waitFor();
  assert.equal(await page.locator('#vehicle-group').inputValue(),'空调与座舱','temperature details open their actual parameter group');
  assert.ok(await page.locator('[data-parameter]').count()>0,'temperature link must not open an empty result');
  await page.getByRole('button',{name:'总览',exact:true}).first().click();
  for(const key of ['rf','hood','trunk','central']){
   await page.locator('.overview-part-'+key).click();
   assert.equal(await page.locator('#overview-part-detail').isVisible(),true);
   await page.locator('.overview-vehicle h2').click();
   assert.equal(await page.locator('#overview-part-detail').isVisible(),false,'outside click closes the detail');
  }
  // The backend emits 已锁车 for its verified central-and-four-door combination.
  await page.evaluate(()=>{state.model.lock={confirmed:true,value:'已锁车'};render();});
  assert.match(await page.locator('.overview-part-central').innerText(),/已锁车/,'render the actual backend lock label');
  assert.equal(await page.locator('.overview-part-central [role="img"]').getAttribute('aria-label'),'已锁');
  await page.evaluate(()=>{state.model.lock={confirmed:true,value:'未锁'};render();});
  assert.match(await page.locator('.overview-part-central').innerText(),/未锁车/);
  await page.evaluate(()=>{state.model.lock={confirmed:true,value:'未锁车'};render();});
  assert.match(await page.locator('.overview-part-central').innerText(),/未锁车/);
  assert.equal(await page.locator('.overview-part-central [role="img"]').getAttribute('aria-label'),'未锁');
  await page.evaluate(()=>{state.model.lock={confirmed:false,value:'已锁车'};render();});
  assert.match(await page.locator('.overview-part-central').innerText(),/锁止未知/,'unconfirmed state cannot show a locked label');
  await page.evaluate(()=>{state.model.lock={confirmed:false,value:'未知'};render();});
  assert.match(await page.locator('.overview-part-central').innerText(),/锁止未知/);
  assert.doesNotMatch(await page.locator('.overview-tyre-readings').innerText(),/25\.6°C|23\.1°C/,'cabin temperature cannot masquerade as tyre temperature');
  assert.doesNotMatch(await page.locator('.overview-vehicle').innerText(),/additionalVehicleStatus|sunroofPos|原始值|全部正常/);
  assert.doesNotMatch(await page.locator('.overview-pm25').innerText(),/ppm|温度更新/);
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
    assert.ok(lf.x+lf.width<=rf.x&&lr.x+lr.width<=rr.x&&lf.y<lr.y&&rf.y<rr.y,'door positions follow the upward-facing car');
    const signatures=await page.locator('.overview-part-hood,.overview-part-rr,.overview-part-lr').evaluateAll(nodes=>nodes.map(node=>{const s=getComputedStyle(node);return [s.color,s.backgroundColor,getComputedStyle(node.querySelector('.overview-part-name')).textDecorationLine].join('|');}));
    assert.equal(new Set(signatures).size,3,`${theme} safe/attention/unknown remain visually distinct`);
    const alignment=await page.locator('.overview-vehicle').evaluate(card=>{
     const box=card.getBoundingClientRect();
     return [...card.querySelectorAll('.overview-environment-reading,.car-tyre-reading')].map(reading=>{
      const label=reading.querySelector('.overview-reading-label,.car-tyre-name').getBoundingClientRect();
      const value=reading.querySelector('strong').getBoundingClientRect();
      const unit=reading.querySelector('.overview-value-unit')?.getBoundingClientRect();
      return {center:Math.abs((label.left+label.right-value.left-value.right)/2),inside:!unit||(unit.left>=box.left&&unit.right<=box.right)};
     });
    });
    assert.ok(alignment.every(item=>item.center<=1&&item.inside),`${theme} ${width} centered values and contained units: ${JSON.stringify(alignment)}`);
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
  await pollSnapshot();
  assert.equal(await page.locator('#overview-part-detail').isVisible(),true,'polling preserves an open floating detail');
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
  await page.locator('.overview-pm25').click();await page.locator('#overview-part-detail [data-overview-parameters]').click();await page.locator('.vehicle-table').waitFor();
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
  assert.equal(await page.locator('#overview-part-detail').isVisible(),false,'owner change closes old detail');
  assert.equal(await page.locator('.overview-status-list button').count(),0,'vehicle switch clears previous issues');
  snapshot=await page.evaluate(()=>{
   state.model.updated_time=null;state.model.updated_at='未知';
   state.model.temperature_updated_time=null;state.model.temperature_updated_at='未知';
   state.model.doors.forEach(d=>{d.door='未知';d.window='未知';d.lock='未知';});
   state.model.doors[0].door='未核实值';state.model.hood=state.model.trunk='未知';
   state.model.lock={confirmed:false,value:'未知'};render();return structuredClone(state);
  });
  assert.match(await page.locator('.hero .freshness').innerText(),/更新时间未知/);
  await page.locator('[data-overview-reading=inside]').click();
  assert.match(await page.locator('#overview-part-detail').innerText(),/更新时间未知/);
  await page.keyboard.press('Escape');
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
  snapshot=await page.evaluate(()=>{
   state.recording={...state.recording,active:null,interval:null,effective_interval:null,status:'failed',error:'采集配置暂不可读或无效，请检查设置与存储权限。'};
   state.monitoring={...state.monitoring,online:false,status:'unavailable'};
   render();return structuredClone(state);
  });
  assert.match(await page.locator('.overview-collection').innerText(),/采集失败.*采样间隔\s*未知 秒/s);
  await page.getByRole('button',{name:'设置',exact:true}).first().click();
  assert.match(await page.locator('#collection-status').innerText(),/采集配置\s*未知/s);
  assert.doesNotMatch(await page.locator('#collection-status').innerText(),/已暂停/);
  const collectionCard=page.locator('.card').filter({has:page.getByRole('heading',{name:'本地轨迹采集',exact:true})});
  assert.match(await collectionCard.innerText(),/采集配置暂不可读/);
  assert.doesNotMatch(await collectionCard.innerText(),/null 秒|undefined 秒/);
  assert.equal(await page.locator('#interval').inputValue(),'');
  const originalStorageBytes=snapshot.storage_bytes;
  for(const [bytes,expected] of [[null,'未知'],['broken','未知'],[-1,'未知'],[0,'0.0 KB'],[2048,'2.0 KB']]){
   snapshot=await page.evaluate(bytes=>{state.storage_bytes=bytes;render();return structuredClone(state);},bytes);
   const sizeRow=collectionCard.locator('.inline-row').filter({has:page.getByText('轨迹数据库大小',{exact:true})});
   assert.equal(await sizeRow.locator('strong').innerText(),expected,'database size must distinguish unknown, zero and actual bytes');
  }
  snapshot=await page.evaluate(bytes=>{state.storage_bytes=bytes;render();return structuredClone(state);},originalStorageBytes);
  await page.locator('[data-detail="settings-notifications"]>summary').click();
  const diagnostics=page.locator('.card').filter({has:page.getByRole('heading',{name:'自动行程与充电通知',exact:true})});
  const unknownDescription=await diagnostics.innerText();
  const outcomes=[];
  for(const status of ['unavailable','degraded','error','unexpected','paused','fresh','unchanged','parked_waiting']){
   snapshot=await page.evaluate(status=>{
    const known=['fresh','unchanged','parked_waiting'].includes(status);
    state.recording={...state.recording,active:known?true:status==='paused'?false:null,interval:known?10:null,status:known?'active':status==='paused'?'paused':'failed'};
    state.monitoring={...state.monitoring,status,online:true};render();return structuredClone(state);
   },status);
   outcomes.push({status,green:await diagnostics.locator('.card-head .pill.good').count()});
  }
  assert.match(await diagnostics.innerText(),/正常采样间隔 10 秒/);
  snapshot=await page.evaluate(()=>{state.recording={...state.recording,active:null,interval:null,status:'failed'};state.monitoring.status='fresh';render();return structuredClone(state);});
  outcomes.push({status:'fresh-unknown-config',green:await diagnostics.locator('.card-head .pill.good').count()});
  assert.deepEqual(outcomes.map(row=>row.green),[0,0,0,0,0,1,1,1,0],'only positively known collecting states appear healthy');
  assert.match(unknownDescription,/正常采样间隔 未知/);
  assert.doesNotMatch(unknownDescription,/每 30 秒/,'unknown configuration must never invent the default interval');
  // Earlier assertions deliberately changed the synthetic owner/request key.
  // Restore the fixture's real identity before testing actual settings writes.
  await page.waitForFunction(()=>!polling&&!busy);
  const identity=await(await page.request.get(f.origin+'/api/state')).json();
  snapshot=await page.evaluate(identity=>{
   for(const key of ['request_key','insights_context','vehicle'])state[key]=identity[key];
   render();return structuredClone(state);
  },identity);
  const recordingRequests=[];
  await page.route('**/api/recording',async route=>{
   recordingRequests.push(route.request().postDataJSON());
   const response=await route.fetch();snapshot=await response.json();
   assert.equal(response.status(),200,'real fixture settings write must succeed');
   await route.fulfill({response,json:snapshot});
  });
  await page.locator('#interval').fill('20');
  await page.getByRole('button',{name:'保存间隔',exact:true}).click();
  await page.waitForFunction(()=>!busy);
  assert.deepEqual(recordingRequests,[],'saving an interval cannot silently choose an unknown switch state');
  assert.match(await page.locator('body').innerText(),/采集开关状态未知/);
  await page.getByRole('button',{name:'开始采集',exact:true}).click();
  await page.waitForFunction(()=>!busy);
  assert.deepEqual(recordingRequests,[{active:true,interval:20}],'explicit start repairs unknown controls using the entered interval');
  assert.equal(await page.evaluate(()=>state.recording.active),true);
  assert.equal(await page.evaluate(()=>state.recording.interval),20);
  assert.equal(await page.evaluate(()=>samplingDraft),null);
  await page.locator('#interval').fill('25');
  await page.getByRole('button',{name:'暂停采集',exact:true}).click();
  await page.waitForFunction(()=>!busy);
  assert.deepEqual(recordingRequests[1],{active:false},'a normal pause does not save the unrelated interval draft');
  assert.equal(await page.locator('#interval').inputValue(),'25');
  assert.equal(await page.evaluate(()=>state.recording.interval),20);
  await page.getByRole('button',{name:'保存间隔',exact:true}).click();
  await page.waitForFunction(()=>!busy);
  assert.deepEqual(recordingRequests[2],{operation:'interval',interval:25});
  assert.equal(await page.evaluate(()=>state.recording.active),false,'saving the interval preserves the explicit paused state');
  snapshot=await page.evaluate(()=>{state.recording.active=true;state.recording.status='active';render();return structuredClone(state);});
  await page.locator('#interval').fill('30');
  await page.getByRole('button',{name:'保存间隔',exact:true}).click();
  await page.waitForFunction(()=>!busy);
  assert.equal(await page.evaluate(()=>state.recording.active),false,'a stale enabled window must not restart collection when saving only the interval');
  assert.equal(await page.evaluate(()=>state.recording.interval),30);
  assert.deepEqual(recordingRequests[3],{operation:'interval',interval:30});
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
  console.log('DESKTOP_STATUS_SUMMARY_PASS: 15 states/all unknown, official photo decode, independent freshness, semantic colors/positions, PM2.5 zero/missing, contextual/reset navigation, polling/owner isolation, failed refresh retention, 8 desktop layouts');
 }catch(error){await f.fail(error);throw error;}finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
