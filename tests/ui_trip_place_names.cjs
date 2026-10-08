const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture(),{page}=f;let manual='',rev=0,fail=false;const writes=[];
 try{
  await page.route(/https:\/\/wprd0[1-4]\.is\.autonavi\.com\/appmaptile\?/,route=>route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aYZkAAAAASUVORK5CYII=','base64')}));
  await page.route('**/api/insights/trip-tags*',async route=>{
   if(route.request().method()==='POST'){
    const body=route.request().postDataJSON();
    if(body.action==='place-name-preview'){
     await route.fulfill({json:{context:body.context,preview_token:'synthetic-preview',affected_count:2,radius_m:body.radius_m,affected:[{id:'report-trip',sides:['start'],within_range:true}],conflicts:[]}});return;
    }
    writes.push(body);
    if(fail){await route.fulfill({status:409,json:{error:'合成版本冲突'}});return;}
    manual=body.action==='place-name-save'?body.name:'';rev++;
    await route.fulfill({json:{context:body.context,name_revision:rev,name_can_undo:true}});return;
   }
   const response=await route.fetch(),data=await response.json();
   data.place_statistics={radius_m:150,name_revision:rev,name_can_undo:rev>0,unknown_departures:0,unknown_arrivals:0,places:[
    {id:'place_1',name_key:'synthetic-anchor',label:manual||'家',name_source:manual?'manual':'commute',manual_name_id:manual?'synthetic-anchor':null,latitude:31.2,longitude:121.4,departures:3,arrivals:2},
    {id:'place_2',name_key:'synthetic-second',label:'测试园区附近',name_source:'address',latitude:31.21,longitude:121.41,departures:2,arrivals:3}],routes:[{start_place:'place_1',end_place:'place_2',count:3}]};
   await route.fulfill({json:data});
  });
  await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();await page.getByRole('button',{name:'行程标签',exact:true}).click();
  await page.getByLabel('标签月份',{exact:true}).fill('2026-09');await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
  await page.getByRole('button',{name:'修改地点名称 家',exact:true}).click();
  await page.getByLabel('地点名称',{exact:true}).fill('地下车库');await page.evaluate(()=>render());
  assert.equal(await page.getByLabel('地点名称',{exact:true}).inputValue(),'地下车库');
  assert.equal(await page.getByRole('button',{name:'保存地点名称',exact:true}).isDisabled(),true);
  await page.getByLabel('命名匹配范围',{exact:true}).selectOption('50');
  await page.getByRole('button',{name:'预览影响行程',exact:true}).click();
  await page.getByText(/本月可能影响 2 趟行程/).waitFor();
  await page.getByRole('button',{name:'保存地点名称',exact:true}).click();
  await page.getByRole('button',{name:'修改地点名称 地下车库',exact:true}).waitFor();
  assert.equal(writes[0].revision,0);assert.equal(writes[0].place_key,'synthetic-anchor');assert.equal(writes[0].date,'2026-09-01');
  assert.match(await page.locator('#tag-place-statistics').innerText(),/地下车库 → 测试园区附近/);
  await page.getByRole('button',{name:'修改地点名称 地下车库',exact:true}).click();
  await page.getByRole('button',{name:'恢复自动名称',exact:true}).click();
  await page.getByRole('button',{name:'修改地点名称 家',exact:true}).waitFor();
  await page.getByRole('button',{name:'修改地点名称 家',exact:true}).click();
  await page.getByLabel('地点名称',{exact:true}).fill('<img src=x onerror=alert(1)>');fail=true;
  await page.getByRole('button',{name:'预览影响行程',exact:true}).click();
  await page.getByRole('button',{name:'保存地点名称',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'合成版本冲突'}).waitFor();
  assert.equal(await page.getByLabel('地点名称',{exact:true}).inputValue(),'<img src=x onerror=alert(1)>');
  assert.equal(await page.locator('#tag-place-statistics img[src="x"]').count(),0);
  fail=false;await page.getByRole('button',{name:'取消地点命名',exact:true}).click();
  await layouts(page,'trip-place-names');
  await page.locator('#tag-place-statistics').screenshot({path:'/tmp/zeekr-insights-qa/trip-place-names-desktop.png'});
  if(!process.env.DESKTOP_ONLY){await page.setViewportSize({width:390,height:844});await page.locator('#tag-place-statistics').screenshot({path:'/tmp/zeekr-insights-qa/trip-place-names-mobile.png'});}
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external.filter(url=>!/^https:\/\/wprd0[1-4]\.is\.autonavi\.com\/appmaptile\?/.test(url)),[]);
  console.log('UI_TRIP_PLACE_NAMES_PASS');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
