// Desktop regression: wheel text must stay outside the rotated vehicle image.
const assert = require('node:assert/strict');
const {fixture} = require('./ui_insight_helpers.cjs');
(async () => {
  let pinnedState=null;
  const f = await fixture({evidenceTestId:'ui_tyre_layout',initialResearch:false,beforeGoto:async page=>{
    await page.route('**/api/state',async route=>{
      const response=await route.fetch();
      await route.fulfill({response,json:pinnedState || await response.json()});
    });
  }});
  const {page} = f;
  try {
    await page.getByRole('button',{name:'刷新状态',exact:true}).click();
    await page.waitForFunction(()=>state?.model&&!busy);
    pinnedState=await page.evaluate(()=>{
      const snapshot=structuredClone(state);
      snapshot.profile.image='/car.svg';
      snapshot.model.tyres=['右前','右后','左前','左后'].map((name,i)=>({name,pressure:`${256.751+i*10} kPa`,temperature:`${21+i}°C`}));
      return snapshot;
    });
    await page.evaluate(snapshot=>{state=snapshot;render();},pinnedState);
    // A real state poll must preserve the synthetic worst-case pressure values.
    await page.waitForFunction(()=>!polling&&!busy);
    await page.evaluate(async()=>{await pollState(true);render();});
    assert.deepEqual(await page.evaluate(()=>state.model.tyres.map(t=>t.pressure)),pinnedState.model.tyres.map(t=>t.pressure),'polling retains distinct wheel evidence');
    for (const view of ['总览']) {
      await page.getByRole('button',{name:view,exact:true}).first().click();
      for (const theme of ['light','dark']) {
        await page.getByLabel('外观',{exact:true}).selectOption(theme);
        for (const width of [1024,1280,1440,1920]) {
          await page.setViewportSize({width,height:1100});
          const diagram=page.locator('.car-tyre-diagram');
          await diagram.scrollIntoViewIfNeeded();
          for(const tyre of pinnedState.model.tyres){
            const reading=diagram.locator(`.car-tyre-reading[data-position="${tyre.name}"]`);
            assert.equal(await reading.locator('strong').innerText(),Number(tyre.pressure.slice(0,-4)).toFixed(1),`${tyre.name}: one decimal, no wheel swap`);
            assert.equal(await reading.locator('.car-tyre-unit').innerText(),'kPa');
            assert.match(await reading.locator('.car-tyre-temp').innerText(),new RegExp(tyre.temperature));
          }
          const [lf,rf,lr,rr]=await Promise.all(['左前','右前','左后','右后'].map(name=>diagram.locator(`[data-position="${name}"]`).boundingBox()));
          assert.ok(lf.x+lf.width<=rf.x&&lr.x+lr.width<=rr.x&&lf.y<lr.y&&rf.y<rr.y,'reading grid keeps left/right and front/rear labels');
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
          assert.ok(await diagram.locator('.car-tyre-art').evaluate(el=>{
            const box=el.getBoundingClientRect(),image=el.querySelector('img').getBoundingClientRect();
            return image.top>=box.top-1&&image.bottom<=box.bottom+1;
          }),`${theme} ${width}: portrait artwork leaves room for hood and trunk labels`);
          const metrics=await diagram.evaluate(el=>({height:el.getBoundingClientRect().height,fontSize:parseFloat(getComputedStyle(el.querySelector('.car-tyre-reading strong')).fontSize),weight:Number(getComputedStyle(el.querySelector('.car-tyre-reading strong')).fontWeight)}));
          assert.ok(metrics.fontSize>=28&&metrics.weight>=700,`${view} pressure must be large and bold: ${JSON.stringify(metrics)}`);
          assert.ok(metrics.height<=900,`${view} compact diagram: ${metrics.height}px`);
          assert.deepEqual(failures,[],`${view} ${theme} ${width}: wheel labels clear of image and within diagram`);
          const collisions=await diagram.evaluate(el=>{
            const labels=[...el.querySelectorAll('.overview-part,.car-tyre-reading')];
            return labels.flatMap((label,i)=>labels.slice(i+1).flatMap(other=>{
              const a=label.getBoundingClientRect(),b=other.getBoundingClientRect();
              return a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top?[[label.textContent,other.textContent]]:[];
            }));
          });
          assert.deepEqual(collisions,[],`${theme} ${width}: door labels and tyre readings remain separate`);
          if(view==='总览') {
            const edges=await page.locator('.overview-health').evaluate(el=>{
              const [map,tyre]=[...el.children].map(node=>node.getBoundingClientRect());
              const status=el.querySelector('#map-status').getBoundingClientRect();
              const headings=[el.querySelector('.location-heading h2'),el.querySelector(':scope>.card>.card-head h2')].map(node=>node.getBoundingClientRect());
              return {height:tyre.height,headingTop:Math.abs(headings[0].top-headings[1].top),top:Math.abs(map.top-tyre.top),bottom:Math.abs(map.bottom-tyre.bottom),mapFooterGap:map.bottom-status.bottom};
            });
            assert.ok(edges.height<=540,`desktop paired cards stay compact: ${JSON.stringify(edges)}`);
            assert.ok(edges.headingTop<=1,`desktop card headings align: ${JSON.stringify(edges)}`);
            assert.ok(edges.top<=1&&edges.bottom<=1,`desktop cards share top and bottom edges: ${JSON.stringify(edges)}`);
            assert.ok(edges.mapFooterGap<=2,`map fills card without blank footer: ${JSON.stringify(edges)}`);
            if(width===1440&&theme==='light')await page.locator('.overview-health').screenshot({path:'/tmp/zeekr-tyre-aligned-cards.png'});
          }
          if(width===1440&&theme==='light')await diagram.screenshot({path:`/tmp/zeekr-tyre-${view==='总览'?'overview':'vehicle'}.png`});
        }
      }
    }
    assert.deepEqual(f.errors,[]);
    console.log('PASS tyre layout: consolidated overview, 4 desktop widths, light/dark');
  } catch(error) {await f.fail(error);throw error;} finally {await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
