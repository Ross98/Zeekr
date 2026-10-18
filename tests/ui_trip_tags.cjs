const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
// Exercise the real controller while a post-save list refresh is held.
async function saveRefreshRace(browser,seed){
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  try{
    await page.addScriptTag({path:require('node:path').join(__dirname,'../zeekr_control/static/trip-tags.js')});
    for(const scenario of ['account','vehicle','return-to-owner','refresh-failure','normal']){
      await page.evaluate(({seed,scenario})=>{
        document.body.innerHTML='<main id="race-root"></main>';
        const root=document.querySelector('main'),state={insights_context:'account-a:vehicle-a'};
        const race={state,reads:0,writes:[],release:null};
        const request=async(url,payload)=>{
          if(url==='/api/insights/commute-rule')return {context:state.insights_context,commute_rule:seed.commute_rule};
          if(payload){race.writes.push(payload);return {context:state.insights_context,revision:seed.revision+1,can_undo:true};}
          race.reads++;
          const result={...structuredClone(seed),context:state.insights_context};
          if(race.reads===2)return new Promise((resolve,reject)=>{race.release=()=>scenario==='refresh-failure'?reject(Error('synthetic refresh failed')):resolve(result);});
          return result;
        };
        const ui=TripTagsPage.create({getState:()=>state,request,escape:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),active:()=>true,time:String});
        for(const type of ['input','change','click'])document['on'+type]=e=>ui.handle(e);
        race.mount=()=>ui.mount(root);window.race=race;race.mount();
      },{seed,scenario});
      await page.locator('[data-tag="load"]').click();
      await page.locator('[data-tag="load"]:not(:disabled)').waitFor();
      await page.locator('[data-tag-event="report-trip"] [data-tag="edit"]').click();
      await page.locator('#tag-labels').fill('旧账号标签');await page.locator('#tag-note').fill('旧账号备注');
      await page.locator('[data-tag="save"]').click();
      await page.waitForFunction(()=>!!race.release);
      assert.equal(await page.evaluate(()=>race.writes.length),1,'one save followed by a held list refresh');
      if(!['normal','refresh-failure'].includes(scenario)){
        await page.evaluate(scenario=>{
          race.state.insights_context=scenario==='vehicle'?'account-a:vehicle-b':'account-b:vehicle-a';race.mount();
          if(scenario==='return-to-owner'){race.state.insights_context='account-a:vehicle-a';race.mount();}
        },scenario);
        await page.locator('[data-tag="load"]').click();
        await page.locator('[data-tag="load"]:not(:disabled)').waitFor();
        await page.locator('[data-tag-event="report-trip"] [data-tag="edit"]').click();
        await page.locator('#tag-labels').fill('新草稿标签');await page.locator('#tag-note').fill('新草稿备注');
      }
      // Drain the resolved promise's continuations without guessing network latency.
      await page.evaluate(async()=>{race.release();await new Promise(resolve=>setTimeout(resolve,0));});
      if(['normal','refresh-failure'].includes(scenario)){
        await page.locator('[data-tag="load"]:not(:disabled)').waitFor();
        assert.equal(await page.locator('#tag-labels').count(),0,scenario+' closes the completed save editor');
        if(scenario==='refresh-failure')assert.match(await page.locator('main').innerText(),/列表尚未刷新/);
      }else{
        // Reopen to expose internal draft loss even when stale DOM stayed visible.
        await page.getByRole('button',{name:'关闭工具面板',exact:true}).click();
        await page.locator('[data-tag-event="report-trip"] [data-tag="edit"]').click();
        assert.equal(await page.locator('#tag-labels').inputValue(),'新草稿标签',scenario+' preserves tags after old refresh');
        assert.equal(await page.locator('#tag-note').inputValue(),'新草稿备注',scenario+' preserves note after old refresh');
        assert.equal(await page.locator('[data-tag="save"]').isEnabled(),true,scenario+' keeps new editor usable');
      }
      assert.equal(await page.evaluate(()=>race.writes.length),1,'old save never submits new draft');
    }
  }finally{await page.close();}
}

(async()=>{
  const f=await fixture({initialResearch:false}),{page}=f;
  try{
    const projection=await page.evaluate(()=>{
      const crs=AmapMaps.crs,source=L.latLng(31.2,121.4);
      const pixel=crs.latLngToPoint(source,16),restored=crs.pointToLatLng(pixel,16);
      return {lat:restored.lat,lng:restored.lng};
    });
    assert.ok(Math.abs(projection.lat-31.2)<1e-7&&Math.abs(projection.lng-121.4)<1e-7);
    const trackRequests=[];
    page.on('request',request=>{if(new URL(request.url()).pathname==='/api/tracks')trackRequests.push(request.url());});
    await page.route('**/api/tracks?**',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(route.request().url().includes('report-partial')?{
      observations:[],segments:[],count:0,gaps:[]
    }:{
      observations:[{trusted:true,plottable:true,latitude:31.2,longitude:121.4,state_time:1},
                    {trusted:true,plottable:true,latitude:31.21,longitude:121.41,state_time:2001}],
      segments:[[{trusted:true,plottable:true,latitude:31.2,longitude:121.4,state_time:1},
                 {trusted:true,plottable:true,latitude:31.21,longitude:121.41,state_time:2001}]],count:2,gaps:[]
    })}));
    await page.route('https://wprd0*.is.autonavi.com/**',route=>route.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg==','base64')}));
    assert.equal(await page.locator('[data-insight-view="tags"]').count(),0);
    await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();
    await page.getByRole('button',{name:'行程标签',exact:true}).click();
    await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
    await page.locator('#tag-events').waitFor();
    await page.locator('[data-tag="load"]:not(:disabled)').waitFor();
    assert.equal(await page.getByRole('heading',{name:'通勤自动标注'}).count(),1);
    await page.getByRole('button',{name:'通勤设置',exact:true}).click();
    assert.equal(await page.getByLabel('家范围半径').inputValue(),'300');
    assert.equal(await page.getByLabel('公司范围半径').inputValue(),'300');
    await page.getByRole('button',{name:'打开选点地图'}).click();
    assert.equal(await page.getByRole('button',{name:'将地图中心设为家'}).count(),1);
    await page.locator('#commute-map').click({position:{x:250,y:160}});
    assert.equal(await page.getByRole('button',{name:'选择家地点'}).getAttribute('aria-pressed'),'false');
    const firstMap=await page.locator('#commute-map').elementHandle();
    await page.locator('#commute-map').click({position:{x:350,y:120}});
    assert.equal(await firstMap.evaluate(el=>el.isConnected),true,'Later map clicks must not move selected home');
    await page.getByRole('button',{name:'选择公司地点'}).click();
    await page.locator('#commute-map').click({position:{x:520,y:180}});
    assert.equal(await page.getByRole('button',{name:'选择公司地点'}).getAttribute('aria-pressed'),'false');
    const completeMap=await page.locator('#commute-map').elementHandle();
    await page.locator('#commute-map').click({position:{x:500,y:100}});
    assert.equal(await completeMap.evaluate(el=>el.isConnected),true,'Map inspection must preserve both selected points');
    assert.ok(await page.locator('#commute-map path.leaflet-interactive').count()>=2);
    assert.equal(await page.locator('#commute-map .commute-pin').count(),2);
    assert.equal(await page.locator('#commute-map img.leaflet-marker-icon').count(),0);
    await page.getByLabel('家范围半径').fill('500');
    await page.getByRole('button',{name:'保存通勤规则'}).click();
    await page.waitForFunction(()=>document.querySelector('#trip-tags-workspace')?.textContent.includes('运行中'));
    assert.equal(await page.getByLabel('家范围半径').inputValue(),'500');
    assert.equal(await page.getByLabel('轨迹日期',{exact:true}).count(),0);
    await page.getByRole('button',{name:'关闭工具面板',exact:true}).click();
    await page.getByLabel('标签月份',{exact:true}).fill('2026-09');
    await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
    assert.match(await page.locator('[data-tag-event="report-trip"] .tag-trip-facts').innerText(),/开始[\s\S]*结束[\s\S]*里程[\s\S]*时长/);
    await page.locator('[data-tag-event="report-trip"] [data-tag="edit"]').click();
    assert.equal(trackRequests.length,0);
    assert.match(await page.locator('#tag-route').innerText(),/查看路线小地图/);
    await page.getByRole('button',{name:'查看路线小地图',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#tag-route .route-sparse-line'));
    assert.equal(trackRequests.length,1);
    await page.getByRole('button',{name:'隐藏路线小地图',exact:true}).click();
    assert.equal(await page.locator('#tag-route .leaflet-container').count(),0);
    await page.getByLabel('行程标签（逗号分隔）',{exact:true}).fill('通勤, 接娃');
    await page.getByLabel('行程备注',{exact:true}).fill('<img src=x onerror=alert(1)> 合成备注');
    await page.getByRole('button',{name:'关闭工具面板',exact:true}).click();
    await page.getByRole('button',{name:'本地记录',exact:true}).click();
    await page.getByRole('button',{name:'行程标签',exact:true}).click();
    await page.locator('[data-tag-event="report-trip"] [data-tag="edit"]').click();
    assert.equal(await page.getByLabel('行程标签（逗号分隔）',{exact:true}).inputValue(),'通勤, 接娃');
    await page.getByLabel('行程标签（逗号分隔）',{exact:true}).focus();
    await page.evaluate(()=>render());
    assert.equal(await page.getByLabel('行程标签（逗号分隔）',{exact:true}).inputValue(),'通勤, 接娃');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'tag-labels');
    await page.getByRole('button',{name:'保存行程标签',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-tag-event="report-trip"]')?.textContent.includes('接娃'));
    await page.locator('[data-tag-event="report-trip"] [data-tag="edit"]').click();
    assert.match(await page.locator('#tag-form').innerText(),/点选已有标签/);
    await page.getByLabel('行程标签（逗号分隔）',{exact:true}).fill('');
    assert.equal(await page.getByRole('button',{name:'选择标签 通勤',exact:true}).getAttribute('aria-pressed'),'false');
    await page.getByRole('button',{name:'关闭工具面板',exact:true}).click();
    await page.locator('[data-tag-event="report-trip-night"] [data-tag="edit"]').click();
    await page.getByRole('button',{name:'选择标签 通勤',exact:true}).click();
    assert.equal(await page.getByLabel('行程标签（逗号分隔）',{exact:true}).inputValue(),'通勤');
    await page.getByRole('button',{name:'保存行程标签',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-tag-event="report-trip-night"]')?.textContent.includes('通勤'));
    await page.getByRole('button',{name:'打开同类比较',exact:true}).click();
    await page.getByLabel('比较标签 A',{exact:true}).selectOption('通勤');
    await page.getByLabel('比较标签 B',{exact:true}).selectOption('接娃');
    assert.match(await page.locator('#tag-comparison').innerText(),/30/);
    assert.match(await page.locator('#tag-comparison').innerText(),/40/);
    await page.getByRole('button',{name:'关闭工具面板',exact:true}).click();
    await page.getByLabel('筛选标签',{exact:true}).selectOption({label:'未标注'});
    assert.equal(await page.locator('[data-tag-event]').count(),1);
    assert.equal(await page.locator('[data-tag-event="report-partial"]').count(),1);
    await page.getByLabel('标签行程完整性',{exact:true}).selectOption('complete');
    assert.equal(await page.locator('[data-tag-event]').count(),0);
    await page.getByLabel('标签行程完整性',{exact:true}).selectOption('all');
    await page.getByLabel('筛选标签',{exact:true}).selectOption('');
    await page.getByLabel('筛选标签',{exact:true}).selectOption({label:'接娃'});
    assert.equal(await page.locator('[data-tag-event]').count(),1);
    assert.equal(await page.locator('[data-tag-event] img').count(),0);
    await page.getByLabel('筛选标签',{exact:true}).selectOption('');
    await page.locator('[data-tag-event="report-partial"] [data-tag="edit"]').click();
    await page.getByRole('button',{name:'查看路线小地图',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#tag-route-map')?.textContent.includes('本趟暂无位置采样'));
    assert.equal(await page.locator('#tag-route .leaflet-container').count(),0);
    await page.getByLabel('行程标签（逗号分隔）',{exact:true}).fill('通勤');
    await page.getByRole('button',{name:'保存行程标签',exact:true}).click();
    await page.getByRole('button',{name:'打开同类比较',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#tag-comparison')?.textContent.includes('片段 1'));
    assert.match(await page.locator('#tag-comparison').innerText(),/22.33/);
    await page.getByRole('button',{name:'关闭工具面板',exact:true}).click();
    await page.locator('[data-tag-event="report-trip"] [data-tag="delete"]').click();
    await page.locator('.tag-trash-details summary').click();
    await page.getByRole('button',{name:'恢复行程标签',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-tag-event="report-trip"]')?.textContent.includes('接娃'));
    await page.locator('[data-tag-event="report-trip-night"] [data-tag="edit"]').click();
    await page.getByLabel('行程标签（逗号分隔）',{exact:true}).fill('通勤, 未标注');
    await page.getByRole('button',{name:'保存行程标签',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#tag-filter')?.textContent.includes('标签：未标注'));
    await page.getByLabel('筛选标签',{exact:true}).selectOption({label:'标签：未标注'});
    assert.equal(await page.locator('[data-tag-event="report-trip-night"]').count(),1);
    await page.getByLabel('筛选标签',{exact:true}).selectOption('untagged');
    assert.equal(await page.locator('[data-tag-event]').count(),0);
    await page.getByLabel('筛选标签',{exact:true}).selectOption('');
    await layouts(page,'trip-tags');
    await page.reload();
    await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();
    await page.getByRole('button',{name:'行程标签',exact:true}).click();
    await page.getByLabel('标签月份',{exact:true}).fill('2026-09');
    await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-tag-event="report-trip"]')?.textContent.includes('接娃'));
    await page.route('**/api/insights/trip-tags?**',async route=>{
      const response=await route.fetch(),body=await response.json();
      const trip=body.events.find(row=>row.id==='report-trip');
      trip.manual_tags=['接娃'];trip.tags=['接娃','通勤'];trip.automatic_commute=true;
      await route.fulfill({response,json:body});
    });
    await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-tag-event="report-trip"]')?.textContent.includes('通勤 · 自动'));
    await page.locator('[data-tag-event="report-trip"] [data-tag="edit"]').click();
    assert.equal(await page.getByLabel('行程标签（逗号分隔）',{exact:true}).inputValue(),'接娃');
    assert.equal(await page.getByRole('button',{name:'取消本趟自动通勤'}).count(),1);
    const seed=await (await page.request.get(f.origin+'/api/insights/trip-tags?date=2026-09-01')).json();
    await saveRefreshRace(f.browser,seed);
    // Reload may leave a read-only research job; navigation cancels that job.
    assert.ok(f.posts.every(url=>url===f.origin+'/api/insights/trip-tags'||
      /^\/api\/analysis\/[a-f0-9]{32}\/cancel$/.test(new URL(url).pathname)));
    assert.ok(f.external.every(url=>/^https:\/\/wprd0[1-4]\.is\.autonavi\.com\//.test(url)));
    assert.deepEqual(f.errors,[]);
    console.log('UI_TRIP_TAGS_PASS: custom/multiple tags, notes escaping/preservation, group comparison and denominators, filters, delete/restore, persistence, desktop themes/zoom/contrast, deferred save refresh context and serial isolation');
  }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
