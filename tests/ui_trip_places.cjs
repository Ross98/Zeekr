const assert=require('node:assert/strict');
const {fixture,layouts,contrast}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture(),{page}=f;const tiles=[];
 try{
  page.on('request',r=>{if(r.url().startsWith('https://tile.openstreetmap.org'))tiles.push(r.url());});
  await page.route('https://tile.openstreetmap.org/**',r=>r.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg==','base64')}));
  await page.route('**/api/insights/trip-tags?*',async route=>{
   const response=await route.fetch(),data=await response.json();
   data.context=await page.evaluate(()=>state.insights_context);
   data.place_statistics={radius_m:150,unknown_departures:1,unknown_arrivals:2,places:[
    {id:'place_1',label:'参考地点 1',latitude:31.2,longitude:121.4,departures:4,arrivals:3},
    {id:'place_2',label:'参考地点 2',latitude:31.21,longitude:121.41,departures:3,arrivals:4}],
    routes:[{start_place:'place_1',end_place:'place_2',count:3}]};
   data.events.forEach(e=>{e.start_place='place_1';e.end_place='place_2';});
   await route.fulfill({json:data});
  });
  await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();
  await page.getByRole('button',{name:'行程标签',exact:true}).click();
  await page.getByLabel('标签月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
  await page.getByRole('heading',{name:'本月出发与到达地点',exact:true}).waitFor();
  assert.match(await page.locator('#tag-place-statistics').innerText(),/150 米/);
  assert.match(await page.locator('#tag-place-statistics').innerText(),/出发地点未知 1 次.*到达地点未知 2 次/s);
  assert.match(await page.locator('#tag-place-statistics').innerText(),/参考地点 1 → 参考地点 2.*3 趟/s);
  assert.match(await page.locator('#tag-events').innerText(),/参考地点 1 → 参考地点 2/);
  assert.equal(await page.locator('#tag-places-map').count(),0);assert.deepEqual(tiles,[]);assert.deepEqual(f.external,[]);
  await page.evaluate(()=>render());
  assert.equal(await page.locator('#tag-places-map').count(),0);
  await layouts(page,'trip-places');
  await page.locator('#tag-place-statistics').screenshot({path:'/tmp/zeekr-insights-qa/trip-places-statistics-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  await page.locator('#tag-place-statistics').screenshot({path:'/tmp/zeekr-insights-qa/trip-places-statistics-mobile.png'});
  await page.evaluate(()=>{const original=L.map;L.map=function(el,options){const map=original(el,options);if(el.id==='tag-places-map')window.testPlacesMap=map;return map;};});
  await page.getByRole('button',{name:'查看地点地图',exact:true}).click();
  await page.locator('#tag-places-map .leaflet-marker-icon').first().waitFor();
  assert.ok(tiles.length>0);
  assert.equal(await page.locator('#tag-places-map img.leaflet-marker-icon').count(),0,'Place markers must not depend on absent image assets');
  assert.equal(await page.locator('#tag-places-map .tag-place-marker').count(),2);
  assert.equal(await page.locator('#tag-places-map .leaflet-tooltip').count(),0,'Avoid permanent overlapping labels');
  await page.locator('.tag-place-table').getByRole('button',{name:'在地图定位 参考地点 2',exact:true}).click();
  await page.locator('#tag-places-map .leaflet-popup').waitFor();
  assert.match(await page.locator('#tag-places-map .leaflet-popup').innerText(),/参考地点 2/);
  const external=page.getByRole('link',{name:'打开地图网站',exact:true});
  assert.equal(await external.getAttribute('href'),'https://www.openstreetmap.org/?mlat=31.21&mlon=121.41#map=18/31.21/121.41');
  assert.equal(await external.getAttribute('rel'),'noopener noreferrer');
  assert.equal(await page.locator('#tag-places-map').evaluate(el=>el.contains(document.activeElement)||el===document.activeElement),true);
  await page.evaluate(()=>render());
  assert.match(await page.locator('#tag-places-map .leaflet-popup').innerText(),/参考地点 2/,'Focused place survives refresh');
  await page.getByRole('button',{name:'查看全部地点',exact:true}).click();
  assert.equal(await page.locator('#tag-places-map .leaflet-popup').count(),0);
  await page.getByRole('button',{name:'隐藏地点地图',exact:true}).click();
  await page.locator('#tag-events').getByRole('button',{name:'在地图定位 参考地点 1',exact:true}).first().click();
  await page.locator('#tag-places-map .leaflet-popup').waitFor();
  assert.match(await page.locator('#tag-places-map .leaflet-popup').innerText(),/参考地点 1/);
  assert.equal(await page.evaluate(()=>testPlacesMap.getZoom()),17);
  assert.ok(await page.evaluate(()=>Math.abs(testPlacesMap.getCenter().lng-121.4)<0.0001));
  await page.locator('.tag-place-routes').getByRole('button',{name:'在地图定位 参考地点 2',exact:true}).click();
  assert.ok(await page.evaluate(()=>Math.abs(testPlacesMap.getCenter().lng-121.41)<0.0001),'Second jump must move the map');
  assert.match(await page.locator('#tag-places-map .leaflet-popup').innerText(),/参考地点 2/);
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('#tag-places-map .leaflet-popup-pane')).opacity==='1');
  await contrast(page);
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>testPlacesMap.invalidateSize({animate:false}));
  await page.locator('#tag-place-statistics').screenshot({path:'/tmp/zeekr-insights-qa/trip-place-jump-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>testPlacesMap.invalidateSize({animate:false}));
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('#tag-place-statistics').screenshot({path:'/tmp/zeekr-insights-qa/trip-place-jump-mobile.png'});
  await page.evaluate(()=>{state.insights_context='synthetic-new-owner';render();});
  await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
  await page.getByRole('heading',{name:'本月出发与到达地点',exact:true}).waitFor();
  assert.equal(await page.locator('#tag-places-map').count(),0);
  await page.getByLabel('标签月份',{exact:true}).fill('2026-08');await page.getByLabel('标签月份',{exact:true}).blur();
  await page.waitForFunction(()=>!document.querySelector('#tag-place-statistics'));
  assert.deepEqual(f.posts,[]);assert.deepEqual(f.errors,[]);
  console.log('UI_TRIP_PLACES_PASS: counts, routes, unknowns, explicit map privacy, month/poll state, themes, mobile and contrast');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
