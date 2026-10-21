const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
(async()=>{
 let sends=0,verifies=0,fail=true;
 const f=await fixture({initialResearch:false,beforeGoto:async page=>{
  await page.route('**/api/vehicle-login/*',async route=>{
   const body=route.request().postDataJSON();
   if(route.request().url().endsWith('/sms')){
    sends++;assert.equal(body.phone,'13800000000');
    await route.fulfill({json:{challenge:'test-challenge',retry_after:60,expires_in:600}});
   }else{
    verifies++;assert.equal(body.challenge,'test-challenge');assert.equal(body.code,'123456');
    await route.fulfill({status:fail?502:200,json:fail?{error:'验证码无效，请重试。'}:{connected:true}});
   }
  });
 }});
 const {page}=f;page.setDefaultTimeout(6000);
 try{
  await page.getByRole('button',{name:'设置',exact:true}).click();
  await page.getByRole('button',{name:'重新连接车辆账号',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'连接车辆账号'});
  await dialog.waitFor();
  await page.getByLabel('副账号手机号',{exact:true}).fill('13800000000');
  await page.getByRole('button',{name:'发送验证码',exact:true}).click();
  await page.getByLabel('短信验证码',{exact:true}).fill('123456');
  await page.getByRole('button',{name:'验证并连接',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'验证码无效'}).waitFor();
  assert.equal(await page.getByLabel('短信验证码',{exact:true}).inputValue(),'');
  assert.equal(await page.getByRole('button',{name:/秒后重发/}).isDisabled(),true);
  // A background rerender must preserve the dialog and its draft.
  await page.getByLabel('短信验证码',{exact:true}).fill('123456');
  await page.evaluate(()=>render());
  assert.equal(await page.getByLabel('短信验证码',{exact:true}).inputValue(),'123456');
  for(const theme of ['light','dark']){
   await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
   await contrast(page,'#vehicle-login-dialog');
  }
  fail=false;
  await page.getByRole('button',{name:'验证并连接',exact:true}).click();
  await dialog.waitFor({state:'detached'});
  assert.equal(sends,1);assert.equal(verifies,2);
  await page.getByRole('button',{name:'重新连接车辆账号',exact:true}).click();
  assert.equal(await page.getByLabel('副账号手机号',{exact:true}).inputValue(),'');
  const screenshotDir=path.join(os.tmpdir(),'zeekr-desktop-previews');fs.mkdirSync(screenshotDir,{recursive:true});
  await page.screenshot({path:path.join(screenshotDir,'zeekr-vehicle-login-preview.png')});
  await page.keyboard.press('Escape');
  await dialog.waitFor({state:'detached'});
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
  console.log('Desktop vehicle login flow passed.');
 }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
