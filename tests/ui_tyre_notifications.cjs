const assert=require('node:assert/strict');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture(),{page}=f;
  try{
    await page.getByRole('button',{name:'设置',exact:true}).first().click();
    await page.getByRole('button',{name:'自定义提醒',exact:true}).click();
    await page.getByRole('button',{name:'读取胎压设置',exact:true}).click();
    await page.locator('#tyre-load').waitFor();
    assert.equal(await page.locator('#tyre-load').inputValue(),'light');
    assert.match(await page.locator('#tyre-thresholds').innerText(),/234.*208.*247/);
    await page.locator('#tyre-load').selectOption('full');
    assert.match(await page.locator('#tyre-thresholds').innerText(),/261.*232.*275.5/);
    await page.getByRole('button',{name:'保存胎压设置',exact:true}).click();
    await page.getByRole('status').filter({hasText:'胎压设置已保存'}).waitFor();
    await page.reload();
    await page.getByRole('button',{name:'读取胎压设置',exact:true}).click();
    await page.locator('#tyre-load').waitFor();
    assert.equal(await page.locator('#tyre-load').inputValue(),'full');
    await page.locator('#tyre-enabled').uncheck();
    await page.getByRole('button',{name:'保存胎压设置',exact:true}).click();
    await page.getByRole('status').filter({hasText:'胎压设置已保存'}).waitFor();
    assert.equal(await page.locator('#tyre-enabled').isChecked(),false);
    const result=await page.request.get(f.origin+'/api/insights/tyres');
    assert.equal((await result.json()).config.enabled,false);
    await layouts(page,'tyre-notifications');
    assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
    assert.ok(f.posts.every(url=>url===f.origin+'/api/insights/tyres'));
    console.log('Tyre settings: thresholds, save, reload, disable, layouts and no external requests passed');
  }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
