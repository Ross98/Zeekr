const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture();const {page}=f;
 try{
  await page.route('**/api/location/map?*',r=>r.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aYZkAAAAASUVORK5CYII=','base64')}));
  await page.route('**/api/location',async route=>{const response=await route.fetch();const data=await response.json();await route.fulfill({json:{...data,approximate_name:'测试公园附近'}});});
  await page.goto(f.origin+'/?p=map');
  await page.locator('#location-info').getByText('定位采集时间未提供',{exact:true}).waitFor();
  assert.equal(await page.locator('#main').getAttribute('data-page'),'overview');
  assert.equal(await page.locator('#overview-location-title').innerText(),'定位地图 · 测试公园附近（推算）');
  assert.equal(await page.locator('[data-page="map"]').count(),0);
  assert.equal(await page.locator('#map').isVisible(),true);
  assert.match(await page.locator('#map-status').innerText(),/缓存位置|候选位置|未绘制位置|部分底图|高德地图|正在读取高德/);
  await page.locator('.amap-position-image').waitFor({state:'visible'});
  await page.getByRole('button',{name:'放大',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.amap-position-image')?.src.includes('zoom=16'));
  await page.getByRole('button',{name:'回到最近位置',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.amap-position-image')?.src.includes('zoom=15'));
  await page.getByRole('button',{name:'隐藏位置',exact:true}).click();
  assert.equal(await page.locator('#map').count(),0);
  await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();
  await page.locator('#location-info').getByText('定位采集时间未提供',{exact:true}).waitFor();
  await page.reload();await page.locator('#map').waitFor({state:'visible'});
  await page.locator('#location-info').getByText('定位采集时间未提供',{exact:true}).waitFor();
  const alignment=await page.evaluate(()=>{const a=document.querySelector('.map-card').getBoundingClientRect(),b=document.querySelector('.location-details').getBoundingClientRect(),h=document.querySelector('.location-heading').getBoundingClientRect(),info=document.querySelector('#location-info');return {top:Math.abs(a.top-b.top),bottom:Math.abs(a.bottom-b.bottom),left:Math.abs(a.left-h.left),scroll:info.scrollHeight>info.clientHeight};});
  assert.ok(alignment.top<1&&alignment.bottom<1&&alignment.left<1);
  assert.ok(alignment.scroll,'Long evidence panel scrolls internally');
  await page.evaluate(()=>{const top=document.querySelector('.overview-location-section').getBoundingClientRect().top+scrollY;scrollTo(0,top-28);});
  await page.screenshot({path:'/tmp/zeekr-overview-location-aligned.png'});
  assert.deepEqual(f.errors,[]);console.log('UI_OVERVIEW_LOCATION_PASS');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
