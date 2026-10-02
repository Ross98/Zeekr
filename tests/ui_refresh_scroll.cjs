// Synthetic pages: background updates must not move the user's reading position.
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture({demo:true,partialCharge:true,automatic:true});
  const {page}=f;
  try{
    let revision=0;
    await page.route('**/api/state',async route=>{
      const response=await route.fetch(),data=await response.json();
      data.read_time=++revision;
      await route.fulfill({json:data});
    });
    const sections=['overview','car','energy','tracks','map','insights','settings'];
    let checks=0;
    for(const width of [1440,390]){
      await page.setViewportSize({width,height:600});
      for(const section of sections){
        // app.js uses lexical state; drive the existing navigation control directly.
        await page.locator(`#navigation [data-page="${section}"]`).evaluate(el=>el.click());
        const selector=section==='insights'?'#insights-workspace [data-insight-view]':'.task-navigation [data-section-task]';
        const tools=await page.locator(selector).evaluateAll(els=>els.map(el=>el.dataset.insightView||el.dataset.sectionTask).filter(Boolean));
        for(const tool of [null,...tools]){
          if(tool)await page.locator(section==='insights'?`[data-insight-view="${tool}"]`:`[data-section-task="${tool}"]`).evaluate(el=>el.click());
          await page.waitForTimeout(150);
          await page.evaluate(()=>{
            document.querySelectorAll('main details').forEach(el=>el.open=true);
            const control=[...document.querySelectorAll('main input,main select,main summary,main button')].find(el=>!el.disabled&&!el.matches('input[type="date"],input[type="month"]')&&el.checkVisibility());
            control?.focus({preventScroll:true});
            window.scrollTo(0,document.documentElement.scrollHeight-innerHeight);
          });
          const before=await page.evaluate(()=>scrollY);
          await page.evaluate(()=>pollState(true));
          await page.waitForTimeout(100);
          const after=await page.evaluate(()=>scrollY);
          assert.ok(Math.abs(after-before)<2,`${section}/${tool||'main'} ${width}: refresh scrolled ${before} -> ${after}`);
          checks++;
        }
      }
    }
    assert.deepEqual(f.errors,[]);
    console.log(`UI_REFRESH_SCROLL_PASS: ${checks} desktop/mobile page and tool refresh checks`);
  }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
