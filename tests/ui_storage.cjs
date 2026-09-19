const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
  const server=spawn('python3',[path.join(__dirname,'storage_fixture.py')]);let browser;
  try{
    const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('fixture timeout')),10000);server.stdout.once('data',data=>{clearTimeout(timer);resolve(Number(String(data).trim()));});server.once('error',reject);});
    browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
    const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`http://127.0.0.1:${port}`);
    await page.locator('[data-page="settings"]').first().click();
    const panel=page.locator('#storage-management'),old=panel.locator('.storage-archive-row').filter({hasText:'2024/12'});
    await old.waitFor();
    assert.match(await panel.innerText(),/企业微信预警.*每 5 分钟/s);
    const current=panel.locator('.storage-archive-row').filter({hasText:'受保护'});
    assert.equal(await current.getByRole('button').isDisabled(),true);
    const preview=async(action)=>{await old.getByRole('button',{name:action,exact:true}).click();await panel.locator('#storage-confirm-input').waitFor();};
    const confirm=async(phrase)=>{await panel.locator('#storage-confirm-input').fill(phrase);await panel.locator('[data-storage-action="execute"]').click();await panel.locator('.storage-confirm').waitFor({state:'detached'});await panel.getByRole('button',{name:'刷新存储状态'}).waitFor();await page.waitForFunction(()=>!document.querySelector('#storage-management [data-storage-action="reload"]').disabled);};
    await preview('移入回收区');
    await panel.locator('#storage-confirm-input').fill('删除');
    assert.equal(await panel.locator('[data-storage-action="execute"]').isDisabled(),true);
    await page.evaluate(()=>render());
    assert.equal(await panel.locator('#storage-confirm-input').inputValue(),'删除','poll render preserves confirmation draft');
    fs.mkdirSync('/tmp/zeekr-storage-qa',{recursive:true});
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1050});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`overflow ${width}`);
      await panel.screenshot({path:`/tmp/zeekr-storage-qa/storage-${width}.png`});
    }
    await panel.getByRole('button',{name:'取消',exact:true}).click();
    assert.equal(await old.count(),1);
    await preview('移入回收区');await confirm('移入回收区 2024/12');
    await old.getByRole('button',{name:'恢复',exact:true}).waitFor();
    await preview('恢复');await confirm('恢复 2024/12');
    await old.getByRole('button',{name:'移入回收区',exact:true}).waitFor();
    await preview('移入回收区');await confirm('移入回收区 2024/12');
    await old.getByRole('button',{name:'永久删除',exact:true}).waitFor();
    await preview('永久删除');assert.match(await panel.locator('.storage-confirm').innerText(),/不可恢复/);
    await confirm('永久删除 2024/12');
    assert.equal(await old.count(),0);assert.equal(await current.count(),1);
    assert.deepEqual(errors,[]);
    console.log('Storage UI passed: health, protection, cancel, session render, trash/restore/purge, 1440/390/320 widths. Synthetic data only.');
  }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
