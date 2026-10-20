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
 await page.getByRole('heading',{name:'按地点看充电',exact:true}).waitFor({timeout:4000});
 assert.equal(await page.locator('.cr-place-map').count(),0);
 assert.equal(requests.filter(p=>p==='/api/insights/charging-place'||p.endsWith('/candidates')).length,0,'no detail or provider request on initial render');
 const summary=page.locator('[data-charge-place-summary]').filter({hasText:'测试广场'});
 assert.match(await summary.innerText(),/2 次/);assert.match(await summary.innerText(),/90.10/);
 await summary.getByRole('button',{name:'查看记录',exact:true}).click();assert.equal(await page.locator('[data-review-record]').count(),2);
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
 await page.waitForFunction(()=>document.querySelector('[data-review-record="report-charge"] .cr-place')?.textContent.includes('验收广场'));
 assert.equal(await page.locator('[data-review-record]').filter({hasText:'验收广场'}).count(),2);
 assert.match(await page.locator('[data-review-record="report-charge"]').innerText(),/测试快充站/);
 await page.locator('[data-review-record="report-charge"] [data-review="place"]').click();await page.getByLabel('场所名称',{exact:true}).waitFor();
 await page.getByRole('button',{name:'查看并校正地图位置',exact:true}).click();
 await page.locator('.cr-place-map.leaflet-container').waitFor();
 const map=page.locator('.cr-place-map');await map.click({position:{x:350,y:160}});
 assert.match(await page.locator('.cr-place-editor').innerText(),/地图位置已调整/);
 const beforeDrag=await page.getByLabel('经度（WGS84）',{exact:true}).inputValue(),pin=await page.locator('.cr-map-pin').boundingBox();
 await page.mouse.move(pin.x+pin.width/2,pin.y+pin.height/2);await page.mouse.down();await page.mouse.move(pin.x+pin.width/2+24,pin.y+pin.height/2+8,{steps:6});await page.mouse.up();
 assert.notEqual(await page.getByLabel('经度（WGS84）',{exact:true}).inputValue(),beforeDrag,'dragging the correction marker updates the WGS84 point');
 await page.getByLabel('场所名称',{exact:true}).fill('单次校正');await page.getByLabel('地点修改范围',{exact:true}).selectOption('single');
 await page.getByRole('button',{name:'预览地点修改',exact:true}).click();assert.match(await page.locator('[data-place-preview]').innerText(),/1 条/);
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
 assert.deepEqual(f.errors,[]);console.log('CHARGING_PLACES_BROWSER_PASS: no default maps/network; whole-session evidence; preview invalidation; history scope; explicit station; correction map; undo; desktop themes');
}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
