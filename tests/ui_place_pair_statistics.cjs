const assert=require('node:assert/strict'),fs=require('node:fs');
const path=require('node:path'),os=require('node:os');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 const screenshotDir=path.resolve(process.env.ZEEKR_TEST_ARTIFACT_DIR||path.join(os.tmpdir(),'zeekr-place-pair-statistics'));
 fs.mkdirSync(screenshotDir,{recursive:true});
 const f=await fixture({initialResearch:false}),{page}=f;
 try{
  let rule,base,posted;
  await page.route('**/api/insights/commute-rule',async route=>{
   if(route.request().method()==='POST'){
    posted=route.request().postDataJSON();rule={revision:2,enabled:true,deleted:false,home:posted.home,work:posted.work};
   }
   if(!base){const response=await route.fetch();base=await response.json();}
   await route.fulfill({json:{...base,commute_rule:rule}});
  });
  await page.route('**/api/insights/trip-tags',async route=>{
   if(route.request().method()!=='POST')return route.continue();
   posted=route.request().postDataJSON();rule={revision:2,enabled:true,deleted:false,home:posted.home,work:posted.work};
   await route.fulfill({json:{context:base.context,...rule}});
  });
  await page.route('**/api/insights/trip-tags?*',async route=>{
   const response=await route.fetch(),data=await response.json(),sample=data.events[0];base=data;
   rule=rule||{revision:1,enabled:true,deleted:false,home:{latitude:31.2,longitude:121.4,radius_m:300},work:{latitude:31.21,longitude:121.41,radius_m:300}};
   data.commute_rule=rule;
   data.place_statistics={...data.place_statistics,places:[{id:'home',label:'瑾家珑熹台',statistics_key:'region:home',commute_alias:'家',departures:2,arrivals:1},{id:'home-old',label:'瑾家珑熹台',statistics_key:'region:home',commute_alias:'家',departures:1,arrivals:0},{id:'work',label:'合成公司园区',statistics_key:'region:work',commute_alias:'公司',departures:1,arrivals:2},{id:'third',label:'合成广场',departures:1,arrivals:1}],unknown_departures:0,unknown_arrivals:0,name_regions:[{id:'home',name:'瑾家珑熹台',latitude:31.2001,longitude:121.4,radius_m:150},{id:'work',name:'合成公司园区',latitude:31.21,longitude:121.41,radius_m:150},{id:'third',name:'合成广场',latitude:31.23,longitude:121.43,radius_m:150}],commute_place_names:{home:'瑾家珑熹台',work:'合成公司园区'},commute_place_regions:{home:'home',work:'work'}};
   data.events=[{...sample,id:'pair-1',start_place:'home',end_place:'work',distance_km:10,duration_seconds:600,estimated_kwh:2,partial:false,tags:['通勤']},{...sample,id:'pair-2',start_place:'home-old',end_place:'work',distance_km:null,duration_seconds:0,estimated_kwh:null,partial:true,tags:['出行'],start_place_evidence:{source:'parking_inferred',sampling_gap_seconds:30}},{...sample,id:'pair-3',start_place:'work',end_place:'home',distance_km:0,duration_seconds:300,estimated_kwh:0,partial:false,tags:['通勤'],end_place_evidence:{source:'parking_inferred',sampling_gap_seconds:25}}];
   data.untagged_count=0;data.groups=[{tag:'通勤'},{tag:'出行'}];await route.fulfill({json:data});
  });
  await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();await page.getByRole('button',{name:'行程标签',exact:true}).click();await page.getByLabel('标签月份',{exact:true}).fill('2026-09');await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
  await page.getByRole('button',{name:'查看与管理地点',exact:true}).click();await page.getByRole('button',{name:'两地点统计',exact:true}).click();
  await page.getByLabel('统计地点 A',{exact:true}).selectOption('region:home');await page.getByLabel('统计地点 B',{exact:true}).selectOption('region:work');
  const stats=page.locator('#tag-pair-statistics');assert.match(await stats.innerText(),/共 3 趟，其中 1 趟观测片段；1 处起点、1 处终点为停车位置推定/);assert.match(await stats.innerText(),/10 km/);assert.match(await stats.innerText(),/2 趟有效样本/);assert.equal(await page.getByLabel('统计地点 A',{exact:true}).locator('option').count(),4);
  await page.getByLabel('两地点统计方向',{exact:true}).selectOption('backward');assert.match(await stats.innerText(),/共 1 趟/);
  await page.getByLabel('两地点行程标签',{exact:true}).selectOption('tag:出行');assert.match(await stats.innerText(),/本月没有符合/);assert.match(await stats.innerText(),/— km/);
  await page.getByLabel('两地点行程标签',{exact:true}).selectOption('');await page.getByLabel('两地点统计方向',{exact:true}).selectOption('both');
  await page.evaluate(()=>render());assert.equal(await page.getByLabel('统计地点 A',{exact:true}).inputValue(),'region:home');
  for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);for(const width of [1440,1280,1024]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}}
  await page.setViewportSize({width:1440,height:1000});await page.getByLabel('外观',{exact:true}).selectOption('dark');
  await page.screenshot({path:path.join(screenshotDir,'place-pair-statistics-preview.png')});
  await page.getByRole('button',{name:'关闭地点面板',exact:true}).click();await page.getByRole('button',{name:'通勤设置',exact:true}).click();
  assert.equal(await page.getByLabel('家地点标签',{exact:true}).inputValue(),'home');assert.equal(await page.getByLabel('公司地点标签',{exact:true}).inputValue(),'work');
  await page.getByLabel('家地点标签',{exact:true}).selectOption('home');assert.equal(posted,undefined);
  await page.getByLabel('公司地点标签',{exact:true}).selectOption('third');assert.equal(posted,undefined);assert.match(await page.locator('#tag-tools-panel').innerText(),/设置有未保存修改/);
  await page.evaluate(()=>render());assert.equal(await page.getByLabel('公司地点标签',{exact:true}).inputValue(),'third');
  await page.screenshot({path:path.join(screenshotDir,'commute-label-choice-preview.png')});
  await page.getByRole('button',{name:'保存通勤规则',exact:true}).click();await page.locator('[data-tag="commute-save"]:not(:disabled)').waitFor();
  assert.equal(posted.home.latitude,31.2,'Selecting current home label preserves centre');assert.equal(posted.home.radius_m,300);assert.equal(posted.work.latitude,31.23);assert.equal(posted.work.radius_m,300);
  await page.getByRole('button',{name:'关闭工具面板',exact:true}).click();await page.getByLabel('标签月份',{exact:true}).fill('2026-10');await page.getByRole('button',{name:'读取行程标签',exact:true}).click();await page.getByRole('button',{name:'查看与管理地点',exact:true}).click();await page.getByRole('button',{name:'两地点统计',exact:true}).click();assert.equal(await page.getByLabel('统计地点 A',{exact:true}).inputValue(),'');assert.equal(await page.getByLabel('统计地点 B',{exact:true}).inputValue(),'');
  assert.deepEqual(f.errors,[]);console.log('UI_PLACE_PAIR_STATISTICS_PASS');
 }catch(error){await f.fail(error);throw error;}finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
