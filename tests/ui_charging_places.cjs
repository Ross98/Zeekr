const assert=require('node:assert/strict');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
(async()=>{const requests=[];const f=await fixture({demo:true,chargingPlaces:true,initialResearch:false,beforeGoto:async p=>{
 p.on('request',r=>requests.push(new URL(r.url()).pathname));
 // Keep synthetic desktop tests independent of the public tile service.
 await p.route('https://wprd0*.is.autonavi.com/**',r=>r.fulfill({status:200,contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e8eeeb"/><path d="M0 48H256M0 180H256M60 0V256M200 0V256" stroke="#fff" stroke-width="14"/><path d="M0 115H256" stroke="#cedad2" stroke-width="4"/><text x="75" y="138" font-size="11" fill="#536b5c">合成测试底图</text></svg>' }));
}});const {page}=f;try{
 page.on('response',async r=>{if(r.url().includes('/api/insights/charging-place')&&r.status()>=400)console.error('Place API rejected:',r.status(),await r.text());});
 await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
 await page.getByLabel('充电月份',{exact:true}).fill('2026-09');await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2026-09');
 assert.equal(await page.locator('.cr-footprint-toggle').count(),1);
 assert.equal(await page.locator('.cr-place-list').isVisible(),false,'station rows are hidden on entry');
 await page.getByRole('button',{name:/本月充电足迹/}).click();
 assert.equal(await page.locator('.cr-place-list').isVisible(),true);
 assert.equal(await page.locator('.cr-place-map').count(),0);
 assert.equal(requests.filter(p=>p==='/api/insights/charging-place'||p.endsWith('/candidates')).length,0,'no detail or provider request on initial render');
 const summary=page.locator('[data-charge-place-summary]').filter({hasText:'测试广场'});
 assert.match(await summary.innerText(),/2 次/);assert.match(await summary.innerText(),/90.10/);
 assert.equal(await summary.locator('button.cr-place-row').count(),1,'whole station row filters records');
 assert.equal(await summary.locator('[data-place-share]').getAttribute('data-place-share'),'100');
 assert.match(await summary.innerText(),/已知花费 100%/);
 const pending=page.locator('[data-charge-place-summary]').filter({hasText:'地点待确认'});
 assert.match(await pending.innerText(),/费用待补/);assert.match(await pending.innerText(),/未计入占比/);
 assert.equal(await pending.locator('[data-place-share]').count(),0);
 await summary.getByRole('button',{name:/查看.*充电记录/}).click();assert.equal(await page.locator('[data-review-record]').count(),2);
 assert.equal(await page.locator('.cr-footprint-toggle').getAttribute('aria-expanded'),'true','filtering preserves disclosure state');
 await page.getByRole('button',{name:'显示全部地点',exact:true}).click();assert.equal(await page.locator('[data-review-record]').count(),3);
 await page.locator('[data-review-record="report-charge"] [data-review="place"]').click();
 await page.getByLabel('场所名称',{exact:true}).waitFor();
 assert.match(await page.locator('.cr-place-editor').innerText(),/整段充电定位|充电期间/);
 assert.match(await page.locator('.cr-place-editor').innerText(),/排除 1/);
 assert.equal(await page.locator('.cr-place-map').count(),0);
 await page.getByRole('button',{name:'查找附近充电站',exact:true}).click();
 await page.getByRole('button',{name:'选择 测试快充站',exact:true}).click();
 assert.equal(await page.getByLabel('充电站名称',{exact:true}).inputValue(),'测试快充站');
 assert.equal(await page.getByRole('button',{name:'保存地点修改',exact:true}).isDisabled(),true);
 await page.getByLabel('场所名称',{exact:true}).fill('验收广场');
 await page.getByLabel('地点修改范围',{exact:true}).selectOption('place');
 await page.getByRole('button',{name:'预览地点修改',exact:true}).click();
 await page.locator('[data-place-preview]').waitFor();
 assert.match(await page.locator('[data-place-preview]').innerText(),/3 条/);
 assert.match(await page.locator('[data-place-preview]').innerText(),/2026-08-10/);
 await page.getByLabel('场所名称',{exact:true}).fill('改动需重预览');
 assert.equal(await page.getByRole('button',{name:'保存地点修改',exact:true}).isDisabled(),true);
 await page.getByLabel('场所名称',{exact:true}).fill('验收广场');await page.getByRole('button',{name:'预览地点修改',exact:true}).click();
 await page.getByRole('button',{name:'保存地点修改',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-review-record="report-charge"] .cr-station-name')?.textContent==='验收广场');
 assert.equal(await page.locator('[data-review-record="report-charge"] .cr-place').innerText(),'测试快充站');
 assert.equal(await page.locator('[data-review-record="report-charge"] .cr-station-name').innerText(),'验收广场');
 assert.equal(await page.locator('[data-review-record]').filter({hasText:'验收广场'}).count(),2);
 assert.match(await page.locator('[data-review-record="report-charge"]').innerText(),/测试快充站/);
 await page.getByRole('button',{name:'撤销最近地点修改',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-review-record="report-charge"] .cr-place')?.textContent.includes('测试广场'));
 await page.locator('[data-review-record="report-charge"] [data-review="place"]').click();await page.getByLabel('场所名称',{exact:true}).waitFor();
 await page.getByRole('button',{name:'查看并校正地图位置',exact:true}).click();
 await page.locator('.cr-place-map.leaflet-container').waitFor();
 const map=page.locator('.cr-place-map');await map.click({position:{x:350,y:160}});
 assert.match(await page.locator('.cr-place-editor').innerText(),/地图位置已调整/);
 await page.waitForFunction(()=>!polling);await page.locator('.cr-map-pin').hover();
 const beforeDrag=await page.getByLabel('经度（WGS84）',{exact:true}).inputValue(),pin=await page.locator('.cr-map-pin').boundingBox();
 const originalPin=await page.locator('.cr-map-pin').elementHandle();
 await page.mouse.down();
 // Force a changed-state poll through the real HTTP path while the pointer is held.
 // The old snapshot value makes this deterministic, independent of the 5 s timer.
 await page.evaluate(async()=>{state.snapshot_revision='charging-drag-before-poll';await pollState(true);});
 assert.notEqual(await page.evaluate(()=>state.snapshot_revision),'charging-drag-before-poll','poll response was applied during the drag');
 assert.equal(await originalPin.evaluate(el=>el.isConnected),true,'polling must keep the held correction marker connected');
 await page.mouse.move(pin.x+pin.width/2+24,pin.y+pin.height/2+8,{steps:6});await page.mouse.up();
 await page.waitForFunction(el=>!el.isConnected,originalPin,{timeout:5000}); // deferred refresh resumes after release

 assert.notEqual(await page.getByLabel('经度（WGS84）',{exact:true}).inputValue(),beforeDrag,'dragging the correction marker updates the WGS84 point');
 const draggedPoint={latitude:Number(await page.getByLabel('纬度（WGS84）',{exact:true}).inputValue()),longitude:Number(await page.getByLabel('经度（WGS84）',{exact:true}).inputValue())};
 assert.ok(Number.isFinite(draggedPoint.latitude)&&Math.abs(draggedPoint.latitude)<=90);
 assert.ok(Number.isFinite(draggedPoint.longitude)&&Math.abs(draggedPoint.longitude)<=180);
 assert.ok(Math.abs(draggedPoint.longitude-Number(beforeDrag))>1e-6,'drag moves a meaningful WGS84 distance');
 await page.getByLabel('场所名称',{exact:true}).fill('单次校正');await page.getByLabel('地点修改范围',{exact:true}).selectOption('single');
 await page.getByRole('button',{name:'预览地点修改',exact:true}).click();assert.match(await page.locator('[data-place-preview]').innerText(),/1 条/);
 await page.getByRole('button',{name:'保存地点修改',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-review-record="report-charge"] .cr-place')?.textContent==='单次校正');
 const savedPoint=await (await page.request.get(f.origin+'/api/insights/charging-place?event=report-charge')).json();
 assert.deepEqual(savedPoint.location,draggedPoint,'dragged WGS84 coordinates persist in the saved record');
 await page.locator('[data-review-record="report-charge"] [data-review="place"]').click();await page.getByLabel('场所名称',{exact:true}).waitFor();
 await page.getByRole('button',{name:'查看并校正地图位置',exact:true}).click();
 assert.equal(Number(await page.getByLabel('纬度（WGS84）',{exact:true}).inputValue()),draggedPoint.latitude);
 assert.equal(Number(await page.getByLabel('经度（WGS84）',{exact:true}).inputValue()),draggedPoint.longitude);
 await page.getByRole('button',{name:'关闭地点详情',exact:true}).click();
 await page.getByRole('button',{name:'撤销最近地点修改',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-review-record="report-charge"] .cr-place')?.textContent.includes('测试广场'));
 await page.locator('[data-review-record="place-unknown"] [data-review="place"]').click();await page.getByLabel('场所名称',{exact:true}).waitFor();
 await page.getByLabel('场所名称',{exact:true}).fill('手动停车场');await page.getByLabel('地点修改范围',{exact:true}).selectOption('place');
 await page.getByRole('button',{name:'预览地点修改',exact:true}).click();await page.getByRole('alert').filter({hasText:'缺少历史定位'}).waitFor();
 await page.getByLabel('地点修改范围',{exact:true}).selectOption('single');await page.getByRole('button',{name:'查看并校正地图位置',exact:true}).click();
 await page.getByLabel('纬度（WGS84）',{exact:true}).fill('31.205');await page.getByLabel('经度（WGS84）',{exact:true}).fill('121.405');
 await page.getByRole('button',{name:'预览地点修改',exact:true}).click();await page.locator('[data-place-preview]').waitFor({timeout:5000}).catch(async e=>{console.error('Editor state:',await page.locator('.cr-place-editor').innerText());throw e;});await page.getByRole('button',{name:'保存地点修改',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-review-record="place-unknown"] .cr-place')?.textContent==='手动停车场');
 // A separate browser context changes the saved record; the first tab must poll/reload it.
 const second=await f.browser.newContext();
 try{const other=await second.request.get(f.origin+'/api/state');const state=await other.json();
  const detail=await (await second.request.get(f.origin+'/api/insights/charging-place?event=place-unknown')).json();
  const payload={context:state.insights_context,event_id:'place-unknown',revision:detail.revision,scope:'single',name:'跨标签同步',station_name:'',latitude:31.205,longitude:121.405,radius_m:75};
  const headers={'Origin':f.origin,'X-Request-Key':state.request_key};
  const plan=await (await second.request.post(f.origin+'/api/insights/charging-place',{headers,data:{...payload,action:'preview'}})).json();
  const saved=await second.request.post(f.origin+'/api/insights/charging-place',{headers,data:{...payload,action:'save',token:plan.token}});assert.equal(saved.status(),200);
  await page.waitForFunction(()=>document.querySelector('[data-review-record="place-unknown"] .cr-place')?.textContent==='跨标签同步',null,{timeout:15000});
 }finally{await second.close();}
 require('node:fs').mkdirSync('/tmp/zeekr-charging-places',{recursive:true});
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);for(const width of [1024,1280,1440]){await page.setViewportSize({width,height:1100});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await contrast(page,'#charging-review');if(width===1440)await page.locator('#charging-review').screenshot({path:`/tmp/zeekr-charging-places/summary-${theme}.png`});}}
 await page.locator('[data-review-record="report-charge"] [data-review="place"]').click();await page.getByLabel('场所名称',{exact:true}).waitFor();
 await page.getByRole('button',{name:'查找附近充电站',exact:true}).click();await page.getByRole('button',{name:'选择 测试快充站',exact:true}).click();
 await page.getByLabel('地点修改范围',{exact:true}).selectOption('place');await page.getByRole('button',{name:'预览地点修改',exact:true}).click();await page.locator('[data-place-preview]').waitFor();
 await page.getByRole('button',{name:'查看并校正地图位置',exact:true}).click();await page.locator('.cr-place-map.leaflet-container').waitFor();
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);await contrast(page,'#charging-review');await page.locator('.cr-place-editor').screenshot({path:`/tmp/zeekr-charging-places/editor-${theme}.png`});}
 await page.getByRole('button',{name:'关闭地点详情',exact:true}).click();
 const beforeMerge=await (await page.request.get(f.origin+'/api/insights/charging-review?date=2026-09-01')).json();
 for(const [event_id,latitude] of [['report-charge',31.2],['place-repeat',31.20156],['place-unknown',null]]){
  const state=await (await page.request.get(f.origin+'/api/state')).json();
  const detail=await (await page.request.get(f.origin+'/api/insights/charging-place?event='+event_id)).json();
  const payload={context:state.insights_context,event_id,revision:detail.revision,scope:'single',name:'合并验收园区',station_name:'合并验收站',latitude,longitude:latitude===null?null:121.4,radius_m:75};
  const headers={'Origin':f.origin,'X-Request-Key':state.request_key};
  const plan=await (await page.request.post(f.origin+'/api/insights/charging-place',{headers,data:{...payload,action:'preview'}})).json();
  assert.equal((await page.request.post(f.origin+'/api/insights/charging-place',{headers,data:{...payload,action:'save',token:plan.token}})).status(),200);
 }
 await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();
 const merged=page.locator('[data-charge-place-summary]').filter({hasText:'合并验收园区'});
 await merged.waitFor();assert.equal(await page.locator('[data-charge-place-summary]').count(),1);
 assert.match(await merged.innerText(),/3 次/);assert.match(await merged.innerText(),/1 次费用待补/);
 assert.equal(await merged.locator('.cr-site-title').innerText(),'合并验收站');
 assert.equal(await merged.locator('.cr-site-venue').innerText(),'合并验收园区');
 assert.doesNotMatch(await merged.innerText(),/坐标缺失|参考位置|AC |DC /);
 assert.doesNotMatch(await merged.innerText(),/地点待确认/);
 const afterMerge=await (await page.request.get(f.origin+'/api/insights/charging-review?date=2026-09-01')).json();
 assert.equal(afterMerge.summary.actual_cents,beforeMerge.summary.actual_cents);
 assert.equal(afterMerge.place_summary[0].actual_cents,beforeMerge.summary.actual_cents);
 await merged.getByRole('button',{name:/查看.*充电记录/}).click();assert.equal(await page.locator('[data-review-record]').count(),3);
 assert.deepEqual(await page.locator('[data-review-record] .cr-place').allTextContents(),['合并验收站','合并验收站','合并验收站']);
 assert.deepEqual(await page.locator('[data-review-record] .cr-station-name').allTextContents(),['合并验收园区','合并验收园区','合并验收园区']);
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);await contrast(page,'#charging-review');await page.locator('.cr-place-summary').screenshot({path:`/tmp/zeekr-charging-places/merged-${theme}.png`});}
 await page.locator('[data-review-record="place-unknown"] [data-review="place"]').click();await page.getByLabel('场所名称',{exact:true}).waitFor();await page.getByRole('button',{name:'查看并校正地图位置',exact:true}).click();await page.getByLabel('纬度（WGS84）',{exact:true}).waitFor();
 assert.equal(await page.getByLabel('纬度（WGS84）',{exact:true}).inputValue(),'','missing coordinates remain in record detail');
 await page.getByRole('button',{name:'关闭地点详情',exact:true}).click();
 let ledger=await (await page.request.get(f.origin+'/api/insights/ledger?date=2026-09-01')).json();
 for(const event_id of ['report-charge','place-repeat']){
  const state=await (await page.request.get(f.origin+'/api/state')).json();
  const response=await page.request.post(f.origin+'/api/insights/ledger',{headers:{'Origin':f.origin,'X-Request-Key':state.request_key},data:{context:state.insights_context,action:'save',revision:ledger.revision,event_id,date:'2026-09-15',source:'unknown',amount:'0',metered_kwh:'40'}});
  assert.equal(response.status(),200);ledger=await response.json();
 }
 await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.cr-site-cost')?.textContent==='0.00 元');
 assert.equal(await page.locator('[data-place-share]').count(),0,'zero total has no invented percentage');
 assert.match(await merged.innerText(),/费用为 0/);assert.match(await merged.innerText(),/1 次费用待补/);
 assert.doesNotMatch(await merged.innerText(),/NaN|Infinity/);
 await page.getByRole('button',{name:/本月充电足迹/}).click();assert.equal(await page.locator('.cr-place-list').isVisible(),false);
 await page.getByLabel('充电月份',{exact:true}).fill('2026-08');await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2026-08');
 assert.equal(await page.locator('.cr-footprint-toggle').getAttribute('aria-expanded'),'false');
 // Pending background refreshes must never retain an editor across owner/navigation changes.
 await page.getByLabel('充电月份',{exact:true}).fill('2026-09');await page.getByRole('button',{name:'刷新充电回顾',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2026-09');
 for(const boundary of ['owner','navigation']){
  await page.locator('[data-review-record="report-charge"] [data-review="place"]').click();await page.getByLabel('场所名称',{exact:true}).waitFor();
  await page.getByRole('button',{name:'查看并校正地图位置',exact:true}).click();
  await page.locator('.cr-map-pin').hover();const heldPin=await page.locator('.cr-map-pin').elementHandle();
  await page.waitForFunction(()=>!polling);await page.mouse.down();
  await page.evaluate(async()=>{state.snapshot_revision='charging-boundary-before-poll';await pollState(true);});
  assert.equal(await heldPin.evaluate(el=>el.isConnected),true);
  await page.evaluate(boundary=>{if(boundary==='owner')state.insights_context='synthetic-other-owner';else page='overview';render();},boundary);
  assert.equal(await heldPin.evaluate(el=>el.isConnected),false,boundary+' change immediately removes the old marker');
  await page.mouse.up();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>resolve())));
  assert.equal(await page.getByLabel('经度（WGS84）',{exact:true}).count(),0,'queued refresh must not revive the old editor');
  if(boundary==='owner'){
   await page.evaluate(()=>pollState(true));
   await page.waitForFunction(()=>document.querySelector('#charging-review')?.dataset.loadedMonth==='2026-09');
  }
 }
 assert.deepEqual(f.errors,[]);console.log('CHARGING_PLACES_BROWSER_PASS: station list, known-cost shares, pending/free costs, whole-row filtering; evidence, preview, polling during drag, saved/reopened WGS84 coordinates, owner/navigation cancellation, undo, desktop themes and confirmed station merging');
}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
