const assert=require('node:assert/strict'),fs=require('node:fs');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture(),{page}=f;
 try{
  await page.evaluate(()=>{
   chargeOwner=state.insights_context;page='energy';chargingTab='process';chargingView='power-soc';chargingPoint=0;
   chargingSession={id:'current',status:'active',start_time:1704067200000,end_time:1704067500000,start_soc:20,end_soc:60,power_kw:0,mode:'dc'};
   chargingSeries={raw_count:6,has_gaps:true,points:[
    {time:1704067200000,soc:20,power_kw:null,segment_id:0},
    {time:1704067260000,soc:30,power_kw:90,segment_id:0},
    {time:1704067320000,soc:null,power_kw:80,segment_id:0},
    {time:1704067380000,soc:45,power_kw:null,segment_id:0},
    {time:1704067440000,soc:55,power_kw:40,segment_id:1},
    {time:1704067500000,soc:60,power_kw:0,segment_id:1}]};
   chargingAnalyticsLoadedKey=chargingAnalyticsKey();render();
  });
  const chart=page.locator('.charging-chart-combined');await chart.waitFor({timeout:3000});
  assert.equal(await page.locator('.charging-chart').count(),1,'one combined chart');
  assert.match(await chart.innerText(),/功率.*动力电池 SOC/s);
  assert.match(await chart.innerText(),/100/);assert.match(await chart.innerText(),/北京时间/);
  const power=chart.locator('.chart-line-power'),soc=chart.locator('.chart-line-soc');
  assert.equal((await power.getAttribute('d')).match(/M/g).length,2,'missing power and segment gap disconnect');
  assert.equal((await soc.getAttribute('d')).match(/M/g).length,3,'missing SOC and segment gap disconnect');
  assert.match(await soc.getAttribute('d'),/H.*V/,'SOC remains stepped');
  assert.equal(await chart.locator('.chart-point-power').count(),4);
  assert.equal(await chart.locator('.chart-point-soc').count(),5);
  const xs=await chart.evaluate(el=>['power','soc'].map(key=>+el.querySelector(`.chart-point-${key}[data-point-index="1"]`).getAttribute('cx')));
  assert.equal(xs[0],xs[1],'different valid ranges still share identical time axis');
  assert.equal(+await chart.locator('.chart-point-power[data-point-index="5"]').getAttribute('cy'),180,'valid zero stays on baseline');
  await page.getByLabel('显示功率').uncheck();assert.equal(await chart.locator('.chart-line-power').count(),0);
  assert.equal(await chart.locator('.chart-line-soc').count(),1);
  assert.equal(await page.evaluate(()=>chargingPoint),0);
  await page.getByLabel('显示功率').check();
  await page.getByLabel('显示动力电池 SOC').uncheck();assert.equal(await chart.locator('.chart-line-soc').count(),0);
  await page.getByLabel('显示动力电池 SOC').check();
  await page.locator('#charging-point').focus();await page.keyboard.press('End');
  assert.equal(await page.evaluate(()=>chargingPoint),5);
  assert.equal(await page.locator('#charging-point').evaluate(el=>el===document.activeElement),true,'keyboard focus survives selection');
  assert.match(await page.locator('.charging-point-picker').innerText(),/60 ?%.*0 kW/s);
  const box=await chart.locator('svg').boundingBox();
  await page.mouse.move(box.x+box.width*(64+672/5)/820,box.y+box.height/2);
  assert.equal(await page.evaluate(()=>chargingPoint),1,'hover selects shared observation');
  assert.equal(await chart.locator('.chart-point.selected').count(),2,'both selected series visible');
  await page.locator('#charging-point').evaluate(el=>{el.value='2';el.dispatchEvent(new Event('input',{bubbles:true}));});
  assert.match(await page.locator('.charging-point-picker').innerText(),/SOC 未提供 \/ 未记录.*80 kW/s);
  for(const theme of ['light','dark'])for(const width of [1440,390,320]){
   await page.setViewportSize({width,height:1000});await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'page overflow');
   fs.mkdirSync('/tmp/zeekr-charging-progress-qa',{recursive:true});
   await contrast(page,'.charging-chart-combined');
   await chart.screenshot({path:`/tmp/zeekr-charging-progress-qa/${theme}-${width}.png`});
  }
  await page.getByLabel('显示功率').uncheck();await page.getByLabel('显示动力电池 SOC').uncheck();
  assert.equal(await chart.locator('.chart-line').count(),0);assert.match(await chart.innerText(),/曲线已隐藏/);
  await page.getByLabel('显示功率').check();await page.getByLabel('显示动力电池 SOC').check();
  await page.evaluate(()=>{chargingSeries.points=[{time:1704067200000,soc:0,power_kw:0,segment_id:0}];chargingPoint=0;renderChargingWorkspace();});
  assert.equal(await chart.locator('.chart-point').count(),2,'single zero samples stay visible');
  assert.equal(await chart.locator('.chart-point-power').getAttribute('cx'),'400.0');
  await page.evaluate(()=>{chargingSeries.points=[{time:1704067200000,soc:null,power_kw:null,segment_id:0}];renderChargingWorkspace();});
  assert.match(await chart.innerText(),/未保存有效功率或电量采样/);assert.equal(await chart.locator('svg').count(),0);
  await page.getByRole('button',{name:'电气细节',exact:true}).click();
  await page.locator('.charging-chart').first().waitFor();
  assert.equal(await page.locator('.charging-chart-combined').count(),0,'electrical retains separate units');
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.posts,[]);
  console.log('UI_CHARGING_PROGRESS_PASS: shared axes, missing/zero/gaps, toggles, selection/focus, themes, widths');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exit(1);});
