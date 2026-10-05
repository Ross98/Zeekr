const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{channel:'chrome'})});
 try{
  const page=await browser.newPage({viewport:{width:900,height:600}});
  await page.setContent('<main id="main"></main>');
  await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,'../zeekr_control/static/navigation-state.js'),'utf8')});
  const result=await page.evaluate(()=>{
   let context='first';RefreshView.context=()=>context;
   const main=document.querySelector('main');
   const markup=count=>`<div style="height:700px"></div><input id="draft" value="unsaved text"><details><summary>读取质量与统计口径 <span>${count} 次读取</span></summary><div style="height:900px"></div></details><div id="rows" style="height:150px;width:150px;overflow:auto"><div style="height:700px;width:600px"></div></div><div style="height:700px"></div>`;
   RefreshView.preserve(main,()=>main.innerHTML=markup(10));
   main.querySelector('details').open=true;
   const input=document.querySelector('#draft');input.focus({preventScroll:true});input.setSelectionRange(2,6);
   document.querySelector('#rows').scrollTop=230;document.querySelector('#rows').scrollLeft=160;
   scrollTo(0,1800);const before=scrollY;
   RefreshView.preserve(main,()=>{
    main.innerHTML=markup(11);
    // A nested repaint must not read a temporarily collapsed page as its baseline.
    RefreshView.preserve(main.querySelector('details'),()=>{});
   });
   const retained={before,after:scrollY,open:main.querySelector('details').open,focus:document.activeElement.id,
    selection:[document.activeElement.selectionStart,document.activeElement.selectionEnd],top:document.querySelector('#rows').scrollTop,left:document.querySelector('#rows').scrollLeft};
   try{RefreshView.preserve(main,()=>{throw Error('synthetic');});}catch{}
   retained.afterError=scrollY;
   // Explicit navigation is allowed to scroll after the synchronous transaction.
   scrollTo(0,0);retained.explicit=scrollY;
   context='another-account';RefreshView.preserve(main,()=>main.innerHTML=markup(12));
   retained.newAccountOpen=main.querySelector('details').open;
   return retained;
  });
  assert.equal(result.after,result.before);assert.equal(result.afterError,result.before);
  assert.equal(result.open,true);assert.equal(result.focus,'draft');assert.deepEqual(result.selection,[2,6]);
  assert.equal(result.top,230);assert.equal(result.left,160);assert.equal(result.explicit,0);assert.equal(result.newAccountOpen,false);
  await page.waitForTimeout(50);assert.equal(await page.evaluate(()=>scrollY),0,'no delayed scroll restoration overrides navigation');
  await page.evaluate(()=>{scrollTo(0,800);RefreshView.guard(()=>scrollTo(0,1000))();});
  assert.equal(await page.evaluate(()=>scrollY),1000,'uninterrupted navigation may restore position');
  await page.evaluate(()=>{window.finishLate=RefreshView.guard(()=>scrollTo(0,0));scrollTo(0,1000);});
  await page.mouse.move(450,300);await page.mouse.wheel(0,300);await page.waitForTimeout(100);
  const newerPosition=await page.evaluate(()=>scrollY);await page.evaluate(()=>finishLate());
  assert.equal(await page.evaluate(()=>scrollY),newerPosition,'late response must respect newer user scroll');
  await page.evaluate(()=>{window.finishLate=RefreshView.guard(()=>scrollTo(0,0));RefreshView.context=()=> 'new-view';});
  await page.evaluate(()=>finishLate());assert.equal(await page.evaluate(()=>scrollY),newerPosition,'late response must respect navigation');
  console.log('UI_REFRESH_VIEW_PASS: synchronous/nested replacement, disclosures, focus/caret, inner scroll, exceptions and account/navigation isolation');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
