// Dense-route correctness runs in CI; hardware timing gates stay in the benchmark.
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
  const begin=Date.parse('2026-09-20T08:00:00+08:00');
  const points=Array.from({length:4001},(_,i)=>({latitude:31.2+i/1000000,longitude:121.4+i/1000000,
    state_time:begin+i*1000+(i>=2000?300000:0),trusted:true,plottable:true,time_label:'合成采样 '+i,time_source:'合成源时间'}));
  const gap={start_time:points[1999].state_time,end_time:points[2000].state_time,duration_seconds:301,reason:'合成采样缺口'};
  let tiles=0;
  const f=await fixture({demo:true,initialResearch:false,beforeGoto:async page=>{
    await page.addInitScript(()=>history.replaceState(null,'','/?p=tracks&s=local&date=2026-09-20'));
    await page.route('https://wprd0*.is.autonavi.com/**',route=>{
      tiles++;return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e5ece6"/></svg>'});
    });
    await page.route('**/api/tracks?*',route=>route.fulfill({json:{observations:points,
      segments:[points.slice(0,2000),points.slice(2000)],gaps:[gap],count:points.length}}));
  }}),{page}=f;
  try{
    await page.getByRole('button',{name:'查询行程',exact:true}).click();
    const ready=()=>page.waitForFunction(()=>localTrips.route?.count===4001&&!localTrips.routeBusy&&map?.getContainer()===document.querySelector('#map'));
    await ready();
    async function check(){
      const drawn=await page.evaluate(()=>{
        const layers=localTrips.layers.getLayers(),at=layer=>[layer.getLatLng().lat,layer.getLatLng().lng];
        return {samples:layers.filter(layer=>layer instanceof L.CircleMarker&&layer.options.radius===4).map(at),
          endpoints:layers.filter(layer=>layer instanceof L.CircleMarker&&layer.options.radius===7).map(layer=>({at:at(layer),label:layer.getTooltip()?.getContent()})),
          gaps:layers.filter(layer=>layer instanceof L.CircleMarker&&layer.options.radius===10).map(layer=>({at:at(layer),label:layer.getTooltip()?.getContent(),dash:layer.options.dashArray})),
          vector_nodes:document.querySelectorAll('#map path,#map canvas').length};
      });
      assert.deepEqual(drawn.samples,points.map(point=>[point.latitude,point.longitude]),'every original sample coordinate is drawn');
      assert.deepEqual(drawn.endpoints,[{at:drawn.samples[0],label:'首个采样点'},{at:drawn.samples.at(-1),label:'末个采样点'}]);
      const label=await page.evaluate(()=>`采样间断 · ${tripDuration(301)}`);
      assert.deepEqual(drawn.gaps,[1999,2000].map(i=>({at:drawn.samples[i],label,dash:'3 3'})),'gap rings only mark the two observed boundaries');
      assert.ok(drawn.vector_nodes<100,'dense route has bounded vector DOM');
      assert.match(await page.locator('.local-gap-details>summary').innerText(),/1 处采样间断/);
    }
    await check();await page.evaluate(()=>{window.checkedMap=map;});
    await page.getByRole('button',{name:'下一点',exact:true}).focus();await page.keyboard.press('Enter');
    assert.equal(await page.locator('#playback').inputValue(),'1');
    assert.deepEqual(await page.evaluate(()=>[mapMarker.getLatLng().lat,mapMarker.getLatLng().lng]),[points[1].latitude,points[1].longitude]);
    await page.locator('[data-local-trip="report-trip-night"]').click();await ready();
    assert.equal(await page.evaluate(()=>map===checkedMap),true,'selection retains map');await check();
    await page.getByLabel('外观',{exact:true}).selectOption('dark');await ready();await check();
    await page.getByRole('button',{name:'隐藏位置',exact:true}).click();assert.equal(await page.locator('#map').count(),0);
    await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();await ready();await check();
    assert.ok(tiles>0);assert.deepEqual(f.errors,[]);assert.deepEqual(f.posts,[]);
    assert.ok(f.external.every(url=>/^https:\/\/wprd0[1-4]\.is\.autonavi\.com\//.test(url)));
    console.log('LOCAL_ROUTE_CANVAS_PASS: 4001 exact samples, endpoints, 301s gap, keyboard playback, selection, theme, privacy');
  }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
