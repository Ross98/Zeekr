const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture();const {page}=f;
  try{
    assert.deepEqual((await page.locator('#navigation button').allTextContents()).slice(0,5),['总览','用车日历','行程与轨迹','能源与充电','用车周报']);
    for(const [key,label,control] of [['calendar','用车日历','#calendar-month'],['report','用车周报','#report-period']]){
      await page.locator(`#navigation [data-page="${key}"]`).click();
      await page.locator(control).waitFor({state:'visible'});
      assert.equal(await page.locator('#main').getAttribute('data-page'),key);
      assert.equal(await page.locator(`#navigation [aria-current="page"]`).innerText(),label);
      await page.waitForFunction(key=>new URLSearchParams(location.search).get('p')===key,key);
      await page.reload();await page.locator(control).waitFor({state:'visible'});
      assert.equal(await page.locator('#main').getAttribute('data-page'),key);
    }
    await page.goBack();await page.locator('#calendar-month').waitFor({state:'visible'});
    await page.goto(f.origin+'/?p=insights&t=report');await page.locator('#report-period').waitFor({state:'visible'});
    assert.equal(await page.locator('#main').getAttribute('data-page'),'report');
    await page.screenshot({path:'/tmp/zeekr-primary-reviews.png'});
    assert.deepEqual(f.errors,[]);console.log('UI_PRIMARY_REVIEWS_PASS');
  }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
