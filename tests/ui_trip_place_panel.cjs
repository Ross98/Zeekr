const assert=require('node:assert/strict');
const fs=require('node:fs');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture({initialResearch:false}),{page}=f;
 try{
  page.setDefaultTimeout(10000);
  await page.route('**/api/insights/trip-tags?*',async route=>{
   const response=await route.fetch(),data=await response.json();
   const places=Array.from({length:24},(_,i)=>({id:`place_${i}`,label:`测试地点 ${i+1}`,name_key:`anchor_${i}`,name_source:'reference',latitude:31.2+i*.001,longitude:121.4,departures:24-i,arrivals:24-i}));
   data.place_statistics={radius_m:150,unknown_departures:1,unknown_arrivals:2,places,name_regions:[{id:'region_1',name:'测试区域',shape:'circle',radius_m:150,latitude:31.2,longitude:121.4}],routes:[{start_place:'place_0',end_place:'place_1',count:5}]};
   data.events.forEach(e=>{e.start_place='place_0';e.end_place='place_1';});
   await route.fulfill({json:data});
  });
  await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();
  await page.getByRole('button',{name:'行程标签',exact:true}).click();
  await page.getByLabel('标签月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
  await page.getByRole('heading',{name:'本月出发与到达地点',exact:true}).waitFor();
  const summary=page.locator('#tag-place-statistics');
  assert.ok((await summary.boundingBox()).height<220,'Default place summary must stay compact with many places');
  assert.equal(await page.locator('.tag-place-table').isVisible(),false,'Full place table stays off the default page');
  const opener=page.getByRole('button',{name:'查看与管理地点',exact:true});
  await opener.click();
  const dialog=page.getByRole('dialog',{name:'地点统计与管理',exact:true});
  await dialog.waitFor();
  assert.equal(await page.locator('.tag-place-table tbody tr').count(),20);
  const box=await dialog.boundingBox();assert.ok(box.x>0&&box.x+box.width<=1440&&box.height<=1000,'Panel fits desktop right edge');
  await page.getByRole('button',{name:'下一页地点',exact:true}).click();
  assert.equal(await page.locator('.tag-place-table tbody tr').count(),4);
  await page.getByRole('button',{name:'已保存区域',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'编辑区域 测试区域',exact:true}).isVisible(),true);
  assert.equal(await page.locator('.tag-place-table').isVisible(),false);
  await page.evaluate(()=>render());assert.equal(await dialog.isVisible(),true,'Refresh preserves open panel and category');
  assert.equal(await page.getByRole('button',{name:'编辑区域 测试区域',exact:true}).isVisible(),true);
  await page.getByRole('button',{name:'常见方向',exact:true}).click();
  assert.match(await page.locator('.tag-place-routes').innerText(),/测试地点 1.*测试地点 2.*5 趟/s);
  await page.keyboard.press('Escape');assert.equal(await dialog.isVisible(),false);
  assert.equal(await opener.evaluate(el=>el===document.activeElement),true,'Closing restores focus to entry');
  await opener.click();await page.getByRole('button',{name:'本月地点',exact:true}).click();
  await page.getByRole('button',{name:'上一页地点',exact:true}).click();
  const scroll=page.locator('.tag-place-table-scroll');
  assert.equal(await scroll.evaluate(el=>el.scrollHeight>el.clientHeight),true,'Long table scrolls inside panel');
  await scroll.evaluate(el=>el.scrollTop=140);await page.evaluate(()=>render());
  assert.ok(await scroll.evaluate(el=>el.scrollTop>=140),'Refresh preserves table scroll');
  await page.getByRole('button',{name:'关闭地点面板',exact:true}).click();
  await page.route(/https:\/\/(?:tile.openstreetmap.org|wprd0[1-4]\.is\.autonavi\.com)\//,r=>r.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg==','base64')}));
  await page.locator('#tag-events').getByRole('button',{name:'在地图定位 测试地点 1',exact:true}).first().click();
  assert.equal(await dialog.isVisible(),true,'Trip endpoint opens the panel automatically');
  await page.locator('#tag-places-map .leaflet-popup').waitFor();
  assert.match(await page.locator('#tag-places-map .leaflet-popup').innerText(),/测试地点 1/);
  for(const theme of ['light','dark']){
   await page.getByRole('button',{name:'关闭地点面板',exact:true}).click();
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   await opener.click();
   for(const width of [1440,1280,1024]){await page.setViewportSize({width,height:900});const bounds=await dialog.boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=width&&bounds.height<=900);}
  }
  fs.mkdirSync('/tmp/zeekr-insights-qa',{recursive:true});
  await page.screenshot({path:'/tmp/zeekr-insights-qa/trip-place-panel-desktop.png'});
  await page.getByRole('button',{name:'关闭地点面板',exact:true}).click();
  await page.getByLabel('标签月份',{exact:true}).fill('2026-08');await page.getByLabel('标签月份',{exact:true}).blur();
  assert.equal(await page.locator('#tag-place-panel').count(),0);
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.posts.filter(url=>!/\/api\/analysis\/[^/]+\/cancel$/.test(url)),[]);
  console.log('UI_TRIP_PLACE_PANEL_PASS: compact default, pagination, categories, refresh, keyboard, endpoint map, desktop themes');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
