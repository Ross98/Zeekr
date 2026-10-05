const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture({demo:true});const {page}=f;
  try{
    await page.evaluate(()=>{state.profile={...state.profile,image:'/car.svg'};page='overview';render();});
    await page.waitForFunction(()=>document.querySelector('.hero-car img')?.complete);
    assert.match(await page.locator('.hero-car img').getAttribute('src'),/\.webp$/);
    const result=await page.evaluate(()=>{
      const hero=document.querySelector('.hero-car img'),tyre=document.querySelector('.car-tyre-art img');
      render();
      return {hero:hero===document.querySelector('.hero-car img'),tyre:tyre===document.querySelector('.car-tyre-art img')};
    });
    assert.deepEqual(result,{hero:true,tyre:true});
    let mapRevision='same';
    await page.route('**/api/location',route=>route.fulfill({json:{valid:true,trusted:true,latitude:31.2,longitude:121.4,coordinate_system:'GCJ-02',map_revision:mapRevision,updated_at:'synthetic'}}));
    let maps=0;
    await page.route('**/api/location/map?**',async route=>{maps++;if(mapRevision!=='same')await new Promise(resolve=>setTimeout(resolve,400));await route.fulfill({path:require('node:path').join(__dirname,'../zeekr_control/static/car-001.png'),contentType:'image/png',headers:{'Cache-Control':'no-store'}});});
    await page.evaluate(()=>{showPosition=true;render();});
    await page.waitForFunction(()=>document.querySelector('#map img')?.complete);
    await page.evaluate(()=>{window.previousMap=document.querySelector('#map img');render();});
    await page.waitForTimeout(300);
    assert.equal(maps,1,'unchanged location must not fetch another map');
    assert.equal(await page.evaluate(()=>window.previousMap===document.querySelector('#map img')),true);
    mapRevision='changed';
    await page.evaluate(()=>render());
    await page.waitForTimeout(100);
    assert.equal(await page.evaluate(()=>window.previousMap===document.querySelector('#map img')),true,'retain old map while replacement loads');
    assert.match(await page.locator('#map-status').innerText(),/上次底图/);
    await page.waitForFunction(()=>document.querySelector('#map img')?.getAttribute('src').includes('changed'));
    assert.equal(maps,2,'changed position gets a new image');
    assert.equal(await page.evaluate(()=>{window.previousMap=document.querySelector('#map img');state.vehicle='different-vehicle';render();return document.querySelector('#map img')===null;}),true,'vehicle switch clears previous image immediately');
    await page.waitForFunction(()=>document.querySelector('#map img')?.complete);
    assert.equal(await page.evaluate(()=>window.previousMap===document.querySelector('#map img')),false);
    await page.evaluate(()=>{showPosition=false;render();});
    require('node:fs').mkdirSync('/tmp/zeekr-image-qa',{recursive:true});
    for(const width of [1440,390]){
      await page.setViewportSize({width,height:1000});
      await page.screenshot({path:`/tmp/zeekr-image-qa/overview-${width}.png`,fullPage:true});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    }
    const cachedPage=await f.browser.newPage();
    try{
      for(let visit=0;visit<2;visit++){
        await cachedPage.goto(f.origin);
        await cachedPage.waitForFunction(()=>state?.model);
        await cachedPage.evaluate(()=>{state.profile={...state.profile,image:'/car.svg'};page='overview';render();});
        await cachedPage.waitForFunction(()=>document.querySelector('.hero-car img')?.naturalWidth>0);
        if(visit===1){
          const transfer=await cachedPage.evaluate(()=>performance.getEntriesByType('resource').filter(entry=>entry.name.includes('car-hero-')).map(entry=>entry.transferSize));
          assert.ok(transfer.length>0);
          assert.ok(transfer.every(bytes=>bytes===0),'repeat visit serves hero from browser cache');
        }
      }
    }finally{await cachedPage.close();}
    assert.deepEqual(f.errors,[]);
    console.log('Image delivery: WebP, node reuse, unchanged map and vehicle isolation passed');
  }finally{await f.close();}
})().catch(error=>{console.error(error);process.exit(1);});
