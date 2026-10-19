// Desktop regression: wheel text must stay outside the rotated vehicle image.
const assert = require('node:assert/strict');
const {fixture} = require('./ui_insight_helpers.cjs');
(async () => {
  const f = await fixture({initialResearch:false});
  const {page} = f;
  try {
    await page.getByRole('button',{name:'刷新状态',exact:true}).click();
    await page.waitForFunction(()=>state?.model);
    await page.evaluate(()=>{
      state.profile.image='/car.svg';
      state.model.tyres=['右前','右后','左前','左后'].map(name=>({name,pressure:'256.751 kPa',temperature:'22°C'}));
      render();
    });
    for (const view of ['总览','车辆']) {
      await page.getByRole('button',{name:view,exact:true}).first().click();
      if(view==='车辆') await page.getByRole('button',{name:'状态总览',exact:true}).click();
      for (const theme of ['light','dark']) {
        await page.getByLabel('外观',{exact:true}).selectOption(theme);
        for (const width of [1024,1280,1440,1920]) {
          await page.setViewportSize({width,height:1100});
          const diagram=page.locator('.car-tyre-diagram');
          await diagram.scrollIntoViewIfNeeded();
          const failures=await diagram.evaluate(el=>{
            const art=el.querySelector('.car-tyre-art').getBoundingClientRect();
            const bounds=el.getBoundingClientRect();
            return [...el.querySelectorAll('.car-tyre-reading')].flatMap(reading=>{
              const r=reading.getBoundingClientRect();
              const overlap=r.left<art.right&&r.right>art.left&&r.top<art.bottom&&r.bottom>art.top;
              const outside=r.top<bounds.top-1||r.bottom>bounds.bottom+1||r.left<bounds.left-1||r.right>bounds.right+1;
              return overlap||outside?[{wheel:reading.dataset.position,overlap,outside}]:[];
            });
          });
          const metrics=await diagram.evaluate(el=>({height:el.getBoundingClientRect().height,fontSize:parseFloat(getComputedStyle(el.querySelector('strong')).fontSize),weight:Number(getComputedStyle(el.querySelector('strong')).fontWeight)}));
          assert.ok(metrics.fontSize>=28&&metrics.weight>=700,`${view} pressure must be large and bold: ${JSON.stringify(metrics)}`);
          assert.ok(metrics.height<=470,`${view} compact diagram: ${metrics.height}px`);
          assert.deepEqual(failures,[],`${view} ${theme} ${width}: wheel labels clear of image and within diagram`);
          if(width===1440&&theme==='light')await diagram.screenshot({path:`/tmp/zeekr-tyre-${view==='总览'?'overview':'vehicle'}.png`});
        }
      }
    }
    assert.deepEqual(f.errors,[]);
    console.log('PASS tyre layout: both views, 4 desktop widths, light/dark');
  } finally {await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
