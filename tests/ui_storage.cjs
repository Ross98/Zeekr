const {startEvidence}=require('../scripts/browser-failure-evidence.cjs');
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
  const server=spawn('python3',[path.join(__dirname,'storage_fixture.py')]);let browser,evidence;
  try{
    const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('fixture timeout')),10000);server.stdout.once('data',data=>{clearTimeout(timer);resolve(Number(String(data).trim()));});server.once('error',reject);});
    browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
    const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];
 evidence=await startEvidence(page,{testId:"ui_storage",synthetic:true});
    page.on('pageerror',error=>errors.push(error.message));
    const GiB=1024**3;
    let sample={status:'healthy',checked_at:Date.now()/1000,capacity_basis:'macos_important_usage',capacity_available_bytes:110*GiB,capacity_used_percent:(1-110/230)*100,reclaimable_bytes:95*GiB,disk_total_bytes:230*GiB,disk_used_bytes:215*GiB,disk_used_percent:215/230*100,disk_free_bytes:15*GiB,inode_used_percent:.8,data_bytes:100,archive_bytes:50,trash_bytes:0};
    await page.route('**/api/storage',route=>route.fulfill({json:{current:sample,monitor:{...sample,monitor_fresh:true}}}));

    await page.goto(`http://127.0.0.1:${port}`);
    await page.locator('[data-page="settings"]').first().click();
    await page.locator('[data-detail="settings-storage"] > summary').click();
    const panel=page.locator('#storage-management'),old=panel.locator('.storage-archive-row').filter({hasText:'2024/12'});
    await old.waitFor();
    assert.match(await panel.innerText(),/macOS估算可用.*110.00 GiB.*即时空闲：15.00 GiB.*预计可回收/s);
    assert.match(await panel.locator('.storage-health-heading').innerText(),/正常/);
    assert.ok(Number(await panel.getByRole('meter').getAttribute('aria-valuenow'))<60);
    assert.match(await panel.innerText(),/Bark 提醒.*企业微信详情.*每 5 分钟/s);
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
    for(const width of [1440,1100]){
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
    sample={...sample,status:'unknown',capacity_basis:'unavailable',capacity_available_bytes:null,capacity_used_percent:null,reclaimable_bytes:null};
    await panel.getByRole('button',{name:'刷新存储状态'}).click();
    await page.waitForFunction(()=>document.querySelector('#storage-management').innerText.includes('macOS可用空间读取失败'));
    assert.match(await panel.locator('.storage-health-heading').innerText(),/巡检异常/);
    assert.equal(await panel.getByRole('meter').count(),0);
    assert.deepEqual(errors,[]);
    console.log('Storage UI passed: health, protection, cancel, session render, trash/restore/purge, desktop1440/1100 widths, macOS effective/raw capacities and native-failure state. Synthetic data only.');
  }catch(error){if(evidence)await evidence.fail(error);throw error;}finally{if(evidence)await evidence.finish();if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
