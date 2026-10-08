// Desktop clicks reveal and focus existing places and saved regions without writes.
process.env.DESKTOP_ONLY='1';
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture(),{page}=f;page.setDefaultTimeout(2500);
 try{
  await page.route(/https:\/\/wprd0\d\.is\.autonavi\.com\//,r=>r.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aYZkAAAAASUVORK5CYII=','base64')}));
  await page.route('**/api/insights/trip-tags?*',async route=>{
   const response=await route.fetch(),data=await response.json();
   const empty=new URL(route.request().url()).searchParams.get('date')==='2026-08-01';
   data.place_statistics={radius_m:150,name_revision:0,name_can_undo:false,unknown_departures:0,unknown_arrivals:0,
    places:empty?[]:[{id:'place_1',label:'地点甲',latitude:31.2,longitude:121.4,departures:1,arrivals:2,name_source:'manual'},
                       {id:'place_2',label:'地点乙',latitude:31.21,longitude:121.41,departures:2,arrivals:1,name_source:'manual'}],
    name_regions:[{id:'region-alone',name:'本月无行程区域',latitude:31.24,longitude:121.44,shape:'polygon',vertices:[[31.24,121.44],[31.24,121.445],[31.245,121.445],[31.245,121.44]]},
      ...Array.from({length:24},(_,i)=>({id:'region-'+i,name:'保存地点 '+i,latitude:31.2+i*.001,longitude:121.4,radius_m:50}))],
    observed_points:[],routes:empty?[]:[{start_place:'place_1',end_place:'place_2',count:1}]};
   data.events.forEach(e=>{e.start_place=empty?null:'place_1';e.end_place=empty?null:'place_2';});
   await route.fulfill({json:data});
  });
  await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();await page.getByRole('button',{name:'行程标签',exact:true}).click();
  await page.getByLabel('标签月份',{exact:true}).fill('2026-09');await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
  const assertJump=async label=>{
   await page.locator('#tag-places-map .leaflet-popup').getByText(label,{exact:true}).waitFor();
   await page.waitForFunction(()=>{const el=document.querySelector('#tag-places-map'),r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;});
   assert.equal(await page.locator('#tag-places-map').evaluate(el=>el.contains(document.activeElement)||el===document.activeElement),true);
  };
  assert.equal(await page.locator('#tag-places-map').count(),0);
  await page.locator('.tag-place-table').getByRole('button',{name:'在地图定位 地点乙',exact:true}).click();await assertJump('地点乙');
  await page.getByRole('button',{name:'隐藏地点地图',exact:true}).click();
  await page.locator('.tag-region-list').getByRole('button',{name:'在地图定位 本月无行程区域',exact:true}).click();await assertJump('本月无行程区域');
  await page.evaluate(()=>render());await assertJump('本月无行程区域');
  await page.locator('.tag-place-routes').getByRole('button',{name:'在地图定位 地点甲',exact:true}).click();await assertJump('地点甲');
  await page.getByRole('button',{name:'隐藏地点地图',exact:true}).click();
  const label=page.locator('.tag-region-list').getByRole('button',{name:'在地图定位 保存地点 0',exact:true});
  await label.focus();await page.keyboard.press('Enter');await assertJump('保存地点 0');
  await page.getByLabel('标签月份',{exact:true}).fill('2026-08');await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
  assert.equal(await page.locator('#tag-places-map').count(),0);
  await page.locator('.tag-region-list').getByRole('button',{name:'在地图定位 本月无行程区域',exact:true}).click();await assertJump('本月无行程区域');
  assert.deepEqual(f.posts,[]);assert.deepEqual(f.errors,[]);
  console.log('DESKTOP_PLACE_LABEL_JUMP_PASS table, routes, saved circle/polygon, keyboard, viewport, refresh and empty month; no writes');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
