// Desktop behavior: dense days, single attribution, unknown != zero, and retained results.
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{const f=await fixture(),{page}=f;try{
 const context=await page.evaluate(()=>state.insights_context);
 const stamp=s=>Date.parse(s+'+08:00');
 const base={category:'same_day',start_trip_id:'a',end_trip_id:'b',start_soc:70,end_soc:69,soc_drop:1,estimated_kwh:.75,status:'comparable',parking_status:'parked',open:false,reason_labels:[],sample_count:4,gap_count:0,p_gear_samples:4,place_label:'公司停车场',place_source:'manual'};
 const events=Array.from({length:5},(_,i)=>({...base,id:'day-'+i,start_time:stamp(`2026-09-29T${String(i+8).padStart(2,'0')}:00:00`),end_time:stamp(`2026-09-29T${String(i+8).padStart(2,'0')}:30:00`),duration_seconds:1800}));
 events.push({...base,id:'cross',category:'overnight',place_label:'机场停车场',place_confidence:'reference',place_reference_age_seconds:120,start_time:stamp('2026-09-30T23:00:00'),end_time:stamp('2026-10-01T01:00:00'),duration_seconds:7200,soc_drop:2,estimated_kwh:1.5});
 events.push({...base,id:'unknown',place_label:'位置未知',start_time:stamp('2026-09-30T08:00:00'),end_time:stamp('2026-09-30T09:00:00'),duration_seconds:3600,status:'uncertain',soc_drop:null,estimated_kwh:null,place_reason:'到达前 5 分钟内没有可信定位',reason_labels:['停车期间有超过 10 分钟的数据缺口'],observation_quality:{read_count:180,fresh_samples:2,repeat_reads:178,invalid_reads:148,last_vehicle_time:stamp('2026-09-30T09:00:00'),last_read_time:stamp('2026-09-30T09:00:03'),max_gap_seconds:3600,unknown_seconds:3600,gap_count:1},observation_gaps:[{start_time:stamp('2026-09-30T08:00:00'),end_time:stamp('2026-09-30T09:00:00'),duration_seconds:3600}]});
 events.push({...base,id:'zero',place_label:'家',start_time:stamp('2026-10-02T08:00:00'),end_time:stamp('2026-10-02T09:00:00'),duration_seconds:3600,soc_drop:0,estimated_kwh:0,charged_soc_gain:5,charging_phases:[{start_time:stamp('2026-10-02T08:15:00'),end_time:stamp('2026-10-02T08:45:00'),duration_seconds:1800,soc_gain:5}]});
 const data={context,start_date:'2026-09-29',end_date:'2026-10-02',calculation_version:4,parking_count:8,comparable_count:7,uncertain_count:1,orphan_count:0,orphan_sessions:[],events};
 let requests=0,fail=false;
 await page.route('**/api/insights/parking?*',route=>{requests++;return route.fulfill(fail?{status:500,json:{error:'合成分析失败'}}:{json:data});});
 await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
 await page.getByRole('button',{name:'停车观测',exact:true}).click();
 await page.locator('#parking-start').fill('2026-09-29');await page.locator('#parking-end').fill('2026-10-02');
 assert.equal(requests,0);
 await page.getByRole('button',{name:'分析停车观测',exact:true}).click();
 await page.locator('[data-parking-session="day-4"]').waitFor();
 assert.equal(await page.locator('[data-parking-date="2026-09-29"] [data-parking-entry]').count(),3);
 await page.getByRole('button',{name:'还有 2 次 · 展开',exact:true}).click();
 assert.equal(await page.locator('[data-parking-date="2026-09-29"] [data-parking-entry]').count(),5);
 const unknown=page.locator('[data-parking-session="unknown"]');
 assert.match(await unknown.innerText(),/位置未知/);assert.match(await unknown.innerText(),/耗电未知/);assert.doesNotMatch(await unknown.innerText(),/0 kWh/);
 const continuation=page.locator('[data-parking-entry="cross"]');
 assert.match(await continuation.innerText(),/跨日/);assert.doesNotMatch(await continuation.innerText(),/1\.5 kWh|下降 2/);
 await unknown.click();assert.match(await page.locator('#parking-detail').innerText(),/数据缺口/);
 assert.match(await page.locator('#parking-detail').innerText(),/有效车辆观测\s*2 条/);
 assert.match(await page.locator('#parking-detail').innerText(),/缓存重复读取\s*178 次/);
 await page.getByText('1 处车辆观测缺口 · 合计 1小时',{exact:true}).click();
 assert.match(await page.locator('.parking-observation-gaps').innerText(),/08:00:00/);
 assert.match(await page.locator('.parking-observation-gaps').innerText(),/09:00:00/);
 assert.match(await page.locator('#parking-detail').innerText(),/到达前 5 分钟内没有可信定位/);
 await page.getByRole('button',{name:'收起停车详情',exact:true}).click();
 await page.getByRole('button',{name:'下一月',exact:true}).click();
 const full=page.locator('[data-parking-session="cross"]');assert.match(await full.innerText(),/机场停车场/);assert.match(await full.innerText(),/2小时/);assert.match(await full.innerText(),/1\.5 kWh/);
 assert.match(await full.innerText(),/参考位置/);
 await full.click();assert.match(await page.locator('#parking-detail').innerText(),/到达前 120 秒/);
 await page.getByRole('button',{name:'收起停车详情',exact:true}).click();
 assert.match(await page.locator('[data-parking-session="zero"]').innerText(),/未见 SOC 下降/);
 assert.match(await page.locator('[data-parking-session="zero"]').innerText(),/0 kWh/);
 await page.locator('[data-parking-session="zero"]').click();
 assert.match(await page.locator('#parking-detail').innerText(),/停车内充电 · 1 个阶段 · SOC 净增加 5 个百分点/);
 assert.match(await page.locator('#parking-detail').innerText(),/30分/);
 await page.getByRole('button',{name:'收起停车详情',exact:true}).click();
 assert.match(await page.locator('[data-parking-date="2026-10-03"]').innerText(),/范围外/);
 assert.equal(requests,1,'month navigation is local');
 await page.locator('.parking-calendar-filters summary').click();
 await page.getByLabel('停车时段',{exact:true}).selectOption('multi_day');
 await page.getByText('没有符合筛选的停车事件',{exact:true}).waitFor();
 await page.getByLabel('停车时段',{exact:true}).selectOption('all');
 await page.getByLabel('耗电可信度',{exact:true}).selectOption('eligible');
 await page.getByRole('button',{name:'上一月',exact:true}).click();
 assert.equal(await page.locator('[data-parking-session="unknown"]').count(),0);
 await page.getByLabel('耗电可信度',{exact:true}).selectOption('all');
 await page.locator('.parking-calendar-filters summary').click();
 await page.getByRole('button',{name:'下一月',exact:true}).click();
 fail=true;await page.getByRole('button',{name:'分析停车观测',exact:true}).click();
 await page.getByRole('alert').waitFor();assert.match(await full.innerText(),/1\.5 kWh/);
 fs.mkdirSync('/tmp/zeekr-parking-calendar-qa',{recursive:true});
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);for(const width of [1440,1280,1024]){
  await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width}`);await contrast(page);
  if(width===1440){await page.evaluate(()=>{scrollTo(0,0);document.querySelector('#toast').hidden=true;});await page.screenshot({path:`/tmp/zeekr-parking-calendar-qa/${theme}.png`,fullPage:true});}
 }}
 // Show a populated month for visual review, rather than only the boundary fixture.
 fail=false;data.start_date='2026-09-01';data.end_date='2026-09-30';data.events=Array.from({length:30},(_,i)=>{
  const date=String(i+1).padStart(2,'0');return {...base,id:'month-'+i,place_label:i%3===0?'家 · 地下车库':'公司停车场',start_time:stamp(`2026-09-${date}T09:10:00`),end_time:stamp(`2026-09-${date}T17:30:00`),duration_seconds:30000};
 });data.events.push({...base,id:'open',place_label:'未命名地点',open:true,status:'uncertain',soc_drop:null,estimated_kwh:null,start_time:stamp('2026-09-30T18:00:00'),end_time:stamp('2026-09-30T19:15:00'),duration_seconds:4500,reason_labels:['缺少可靠的停车起止边界']});
 data.parking_count=31;data.uncertain_count=1;
 await page.locator('#parking-start').fill('2026-09-01');await page.locator('#parking-end').fill('2026-09-30');await page.getByRole('button',{name:'分析停车观测',exact:true}).click();
 await page.locator('[data-parking-session="month-0"]').waitFor();
 assert.match(await page.locator('[data-parking-session="open"]').innerText(),/已观测 1小时15分/);
 assert.match(await page.locator('[data-parking-session="open"]').innerText(),/后续行程未记录/);
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);for(const width of [1440,1280,1024]){
  await page.setViewportSize({width,height:1000});await page.locator('.parking-calendar-filters summary').click();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`open filters ${theme} ${width}`);await contrast(page);
  await page.locator('.parking-calendar-filters summary').click();
  if(width===1440){await page.locator('.parking-calendar-panel').screenshot({path:`/tmp/zeekr-parking-calendar-qa/month-${theme}.png`});}
 }}
 assert.deepEqual(f.errors,[]);console.log('DESKTOP_PARKING_CALENDAR_PASS');
}finally{await f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
