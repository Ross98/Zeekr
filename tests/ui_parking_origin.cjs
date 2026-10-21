const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture({initialResearch:false}),{page}=f;
  try{
    let inferred=true,automatic=false,startGap=33.57,endGap=30;
    await page.route('**/api/insights/trip-tags*',async route=>{
      if(route.request().method()!=='GET')return route.continue();
      const response=await route.fetch(),data=await response.json();
      const row=data.events[0];
      if(!row)return route.fulfill({json:data});
      if(inferred){
        row.start_place='synthetic-parking';
        row.start_place_evidence={source:'parking_inferred',sample_time:row.start_time,sampling_gap_seconds:automatic?startGap:16437.121,reviewed:!automatic};
        row.end_place='synthetic-parking';
        row.end_place_evidence={source:'parking_inferred',sample_time:row.end_time+90000,sampling_gap_seconds:automatic?endGap:1190.103,reviewed:!automatic};
        row.partial=!automatic;
        data.place_statistics.places.push({id:'synthetic-parking',label:'合成停车地点',latitude:31.2,longitude:121.4,departures:1,arrivals:0});
      }
      await route.fulfill({json:data});
    });
    await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();
    await page.getByRole('button',{name:'行程标签',exact:true}).click();
    await page.getByLabel('标签月份',{exact:true}).fill('2026-09');
    await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
    const card=page.locator('#tag-events [data-tag-event]').first();
    const details=card.locator('.tag-record-details');
    async function openDetails(){
      await page.locator('[data-tag="load"]:not(:disabled)').waitFor();
      if(!await details.evaluate(el=>el.open))await details.locator('summary').click();
    }
    async function checkGaps(start,end){
      const gaps=details.locator('p').filter({hasText:/定位采样缺口约/});
      await gaps.nth(1).waitFor();
      assert.deepEqual(await gaps.allTextContents(),[start,end].map(value=>`定位采样缺口约 ${value}，间隔内移动情况未知。`),'Both endpoint gaps retain their order and precision');
    }
    await page.locator('[data-tag="load"]:not(:disabled)').waitFor();
    assert.equal(await details.evaluate(el=>el.open),false,'Tag record evidence defaults collapsed');
    await openDetails();
    const note=details.getByText('起点由相邻停车位置推定，非可信 GPS 定位。',{exact:true});
    await note.waitFor();
    const endNote=details.getByText('终点由相邻停车位置推定，非可信 GPS 定位。',{exact:true});
    await endNote.waitFor();
    await checkGaps('4 小时 34 分钟','19.84 分钟');
    assert.match(await card.innerText(),/合成停车地点\s*→\s*合成停车地点/);
    assert.match(await card.innerText(),/观测片段/);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    automatic=true;
    await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
    await openDetails();
    await checkGaps('33.57 秒','30 秒');
    assert.match(await card.innerText(),/完整记录/);
    assert.doesNotMatch(await card.innerText(),/观测片段/);
    assert.equal(await note.count(),1);
    assert.equal(await endNote.count(),1);
    for(const [seconds,display] of [[0.25,'0.25 秒'],[59.9,'59.9 秒'],[60,'1 分钟']]){
      startGap=endGap=seconds;
      await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
      await openDetails();
      await checkGaps(display,display);
    }
    inferred=false;
    await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
    await page.locator('[data-tag="load"]:not(:disabled)').waitFor();
    await openDetails();
    assert.equal(await note.count(),0);
    assert.equal(await page.locator('#tag-events').getByText(/定位采样缺口约/).count(),0);
    assert.equal(await endNote.count(),0);
    assert.equal(await page.locator('#tag-events').getByText(/采样缺口约/).count(),0);
    assert.deepEqual(f.errors,[]);
    console.log('UI_PARKING_ORIGIN_DESKTOP_PASS');
  }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
