// Vehicle marker stays tied to its displayed cached map, including pending/error states.
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 let revision='first',trusted=false,valid=true,mode='ok',release,requested=0;
 const map='<svg xmlns="http://www.w3.org/2000/svg" width="750" height="400"><rect width="750" height="400" fill="#edf1ed"/><path d="M0 200H750M375 0V400" stroke="#bacac6" stroke-width="2"/></svg>';
 const f=await fixture({initialResearch:false,beforeGoto:async page=>{
  await page.route('**/api/location',r=>r.fulfill({json:{valid,trusted,latitude:31.2,longitude:121.4,coordinate_system:'GCJ-02',map_revision:revision,updated_at:'合成缓存时间',approximate_name:'测试公园附近'}}));
  await page.route('**/api/location/map?*',async r=>{requested++;if(mode==='delayed')await new Promise(resolve=>release=resolve);if(mode==='error')return r.fulfill({status:503,body:'unavailable'});await r.fulfill({contentType:'image/svg+xml',body:map});});
 }});const {page}=f;
 const marker=()=>page.locator('.location-position-marker');
 try{
  await page.waitForFunction(()=>document.querySelector('#map img')?.naturalWidth>0);
  assert.equal(await marker().count(),1,'exactly one visible vehicle marker after a map loads');
  assert.match(await marker().innerText(),/车辆缓存位置/);
  assert.match(await marker().getAttribute('aria-label'),/候选位置/);
  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   for(const width of [1440,1280,1024]){
    await page.setViewportSize({width,height:1000});
    const geometry=await page.locator('#map').evaluate(el=>{
     const image=el.querySelector('img').getBoundingClientRect(),dot=el.querySelector('.location-marker-dot').getBoundingClientRect(),mark=el.querySelector('.location-position-marker').getBoundingClientRect(),bounds=el.getBoundingClientRect();
     return {markerHeight:mark.height,mapHeight:bounds.height,topInset:mark.top-bounds.top,dx:Math.abs(dot.x+dot.width/2-image.x-image.width/2),dy:Math.abs(dot.y+dot.height/2-image.y-image.height/2),clipped:mark.top<bounds.top||mark.left<bounds.left||mark.right>bounds.right||mark.bottom>bounds.bottom};
    });
    assert.ok(geometry.dx<1&&geometry.dy<1&&!geometry.clipped,`${theme} ${width} vehicle anchor at displayed image center: ${JSON.stringify(geometry)}`);
    if(width===1440)await page.locator('#map').screenshot({path:`/tmp/zeekr-location-marker-${theme}.png`});
   }
  }
  await page.evaluate(()=>{window.originalMap=document.querySelector('#map img');window.originalMarker=document.querySelector('.location-position-marker');render();});
  await page.waitForFunction(()=>!document.querySelector('#map-status').textContent.includes('正在核对'));
  assert.equal(await page.evaluate(()=>window.originalMap===document.querySelector('#map img')&&window.originalMarker===document.querySelector('.location-position-marker')),true,'unchanged map retains both nodes');
  mode='delayed';revision='moved';trusted=true;
  const before=requested;await page.evaluate(()=>render());await page.waitForFunction(()=>document.querySelector('#map-status').textContent.includes('正在更新底图'));
  assert.equal(await page.evaluate(()=>window.originalMarker===document.querySelector('.location-position-marker')),true,'keep old marker until replacement map has loaded');
  assert.match(await marker().getAttribute('aria-label'),/候选位置/,'pending trusted response cannot relabel the old map');
  while(!release)await new Promise(resolve=>setTimeout(resolve,10));release();
  await page.waitForFunction(()=>document.querySelector('#map img')?.src.includes('moved'));
  assert.equal(requested,before+1);assert.match(await marker().getAttribute('aria-label'),/非实时/);assert.doesNotMatch(await marker().getAttribute('aria-label'),/候选位置/);
  mode='error';revision='failed';await page.evaluate(()=>render());await page.waitForFunction(()=>document.querySelector('#map-status').textContent.includes('新底图加载失败'));
  assert.equal(await marker().count(),1);assert.ok(await page.locator('#map img').getAttribute('src').then(s=>s.includes('moved')),'failed image retains previous map and marker');
  mode='delayed';revision='other';release=null;
  await page.evaluate(()=>{state.vehicle='other-car';render();});
  assert.equal(await marker().count(),0,'switching vehicle clears the previous vehicle marker immediately');
  while(!release)await new Promise(resolve=>setTimeout(resolve,10));release();await page.waitForFunction(()=>document.querySelector('#map img')?.src.includes('other'));
  valid=false;await page.evaluate(()=>render());await page.waitForFunction(()=>document.querySelector('#map-status').textContent==='未绘制位置');assert.equal(await marker().count(),0,'invalid location has no marker');
  await page.getByRole('button',{name:'隐藏位置',exact:true}).click();assert.equal(await marker().count(),0,'hide position hides marker');
  valid=true;mode='ok';revision='visible-again';await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();await marker().waitFor();
  assert.deepEqual(f.errors,[]);console.log('PASS vehicle marker: center/contain, six desktop themes/widths, unchanged nodes, pending/error retention, vehicle switch, invalid coordinates');
 }finally{release?.();await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
