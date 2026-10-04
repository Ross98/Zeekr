const assert=require('node:assert/strict');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture({demo:true,partialCharge:true,automatic:true}),{page}=f;
 try{
  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   await page.setViewportSize({width:390,height:844});
   await page.locator('#navigation [data-page="overview"]').evaluate(el=>el.click());
   const bottom=await page.locator('.overview-metrics .metric').evaluateAll(els=>Math.max(...els.slice(0,2).map(el=>el.getBoundingClientRect().bottom)));
   const navigationTop=await page.locator('#mobile-navigation').evaluate(el=>el.getBoundingClientRect().top);
   assert.ok(bottom<=navigationTop,`${theme}: battery and range bottom ${bottom} must fit above navigation ${navigationTop}`);
   assert.match(await page.locator('.hero').innerText(),/云端缓存.*不代表实时状态/s);
   assert.match(await page.locator('.overview-temperature').innerText(),/车内温度.*车外温度.*未知/s);
   assert.match(await page.locator('.overview-temperature').innerText(),/温度更新于.*与整车状态可能不同步/s);
   const targets=await page.locator('.closure-summary,.overview-attention button,.overview-temperature .text-link').evaluateAll(els=>els.filter(el=>el.checkVisibility()).map(el=>({text:el.textContent,height:el.getBoundingClientRect().height})));
   assert.ok(targets.every(el=>el.height>=44),JSON.stringify(targets));
   for(const scope of ['.footer','.sidebar-bottom','.status-footer','.overview-temperature','.hero'])await contrast(page,scope);
   for(const width of [320,390,1440]){
    await page.setViewportSize({width,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${theme} ${width} no overflow`);
   }
  }
  await page.setViewportSize({width:320,height:844});
  await page.evaluate(()=>{state.monitoring.error='认证状态异常：需要重新登录';state.monitoring.events=[{kind:'trip_end',delivery:'failed'}];render();});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'long recovery actions wrap without overflow');
  assert.equal(await page.getByRole('button',{name:'查看处理',exact:true}).isVisible(),true);
  assert.deepEqual(f.errors,[]);
  console.log('UI_OVERVIEW_LAYOUT_PASS: core metrics above mobile navigation, retained cache/temperature evidence, contrast and reflow');
 }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
