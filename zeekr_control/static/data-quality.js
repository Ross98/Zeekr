(function(root){
  'use strict';
  const dateAt=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const number=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value):'未知';
  const labels={new:'有效时间推进',revision:'同时间修订',repeat:'重复读取',invalid:'陈旧或异常时间'};
  const issueLabels={stale:'采集时已陈旧',unknown_time:'车辆时间未知',future_time:'车辆时间超前',regression:'车辆时间倒退',revisited_time:'再次回到已观测时间'};
  const gapLabels={leading:'范围起点至首条读取',between:'相邻读取之间',trailing:'末条读取至截止时间',empty:'范围内没有读取'};
  function create({getState,request,escape:esc,active,time,navigate}){
    let node=null,owner='',start=dateAt(Date.now()-6*86400000),end=dateAt(Date.now());
    let data=null,attempted=false,loading=false,error='',serial=0,selected='',dayPage=0,gapPage=0;
    const context=()=>getState()?.insights_context||'';
    const valid=(token,identity)=>serial===token&&owner===identity&&context()===identity;
    const button=(label,action,disabled=false)=>`<button class="button secondary" data-quality="${action}" ${disabled?'disabled':''}>${label}</button>`;
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const interval=Number(getState()?.recording?.effective_interval);
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">数据质量雷达</span><h2>先看证据，再看结论</h2><p>时间有没有推进，读到了多少，哪些时段留下空白。</p></div><span class="insight-source">归档时间元数据 · 只读</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>质量分析开始日期<input id="quality-start" type="date" value="${esc(start)}"></label><label>质量分析结束日期<input id="quality-end" type="date" value="${esc(end)}"></label>${button('分析数据质量','load',!owner||!start||!end)}</div>${!data&&!loading&&owner?'<p class="insight-note">选择查询条件后，点击查询按钮显示结果。</p>':''}${loading?'<p role="status">正在读取时间元数据…</p>':''}${error?`<p class="notice error" role="alert">${esc(error)}${data?' · 保留上次结果与原日期范围。':''}</p>`:''}${!owner?'<p>等待当前账号的车辆缓存后，可分析历史质量。</p>':''}<p class="insight-note">最多 31 天。这里统计历史采集当时的时间关系；不因记录年代久而把它判成陈旧。</p><p class="insight-note">默认采集间隔 60 秒；确认下电、静止且未充电满 10 分钟后，可降至 300 秒。当前页面显示间隔 ${Number.isFinite(interval)&&interval>0?number(interval)+' 秒':'未知'}；当前策略不代表历史每一刻的节奏。</p></section>
        ${data?`<section class="card insight-panel"><h3 id="quality-range">结果范围：${data.start_date} 至 ${data.end_date}</h3><p class="insight-note">统计截至 ${esc(time(data.as_of))}；未来时段不算缺口。</p><div class="insight-metrics" id="quality-totals"><div><span>归档读取总数</span><strong>${data.reads}</strong></div>${Object.entries(labels).map(([key,label])=>`<div><span>${label}</span><strong>${data.counts[key]}</strong><small>${data.reads?number(data.counts[key]/data.reads*100)+'%':'无读取，比例未知'}</small></div>`).join('')}</div><div class="quality-composition" aria-hidden="true">${Object.keys(labels).map(key=>`<span class="quality-${key}" style="width:${data.reads?data.counts[key]/data.reads*100:0}%"></span>`).join('')}</div><p class="insight-note">四类互斥，总和等于读取数。陈旧或异常优先；其余再分重复、修订和时间推进。同一时间修订不算新的车辆时刻，倒退后返回旧时刻也不重复计数。</p><p class="insight-note">${Object.entries(data.issues).map(([key,count])=>`${issueLabels[key]} ${count}`).join(' · ')}。异常标记可重叠，不相加当总数。</p><p class="insight-note">来源：后台 ${data.sources.monitor} 次 · 手动 ${data.sources.manual} 次 · 未知 ${data.sources.unknown} 次。重复只说明缓存相同，不证明采集失败或车辆故障。</p></section>
        <section class="card insight-panel"><h3>车辆时间到云端读取时间的延迟</h3><div class="quality-delays">${data.delay.bins.map(row=>`<div class="quality-delay-row"><span>${row.label}</span><div aria-hidden="true"><i style="width:${Math.max(...data.delay.bins.map(b=>b.count))?row.count/Math.max(...data.delay.bins.map(b=>b.count))*100:0}%"></i></div><strong>${row.count} 次</strong></div>`).join('')}</div><div class="parking-row-values"><span>中位数（P50）<strong>${number(data.delay.p50_seconds)} 秒</strong></span><span>95% 分位数（P95）<strong>${number(data.delay.p95_seconds)} 秒</strong></span><span>最大时间差<strong>${number(data.delay.max_seconds)} 秒</strong></span><span>平均时间差<strong>${number(data.delay.mean_seconds)} 秒</strong></span></div><p class="insight-note">延迟 = 云端读取时间 − 车辆时间。统计量使用 ${data.delay.sample_count} 个有效非负时间差，含陈旧读取；负值单列，另有 ${data.delay.unknown_count} 次时间差未知。此值不是网络耗时。归档写入较晚与车辆更新较晚是不同情况。</p></section>
        <section class="card insight-panel"><div class="insight-heading"><h3>每日读取覆盖</h3>${button('清除日期筛选','clear',!selected)}</div><p class="insight-note">每半小时一个时段，含正在进行的时段。“有读取”与“有有效时间推进”分别计数；时段命中不等于车辆连续在线，也不表示整段车况已知。点击日期筛选下方间隔。</p><div id="quality-days"></div></section><section class="card insight-panel"><div class="insight-heading"><h3 id="quality-gap-heading"></h3>${button('查看所选日快照','snapshots',!selected)}</div><p class="insight-note">仅列超过 ${data.gap_threshold_seconds/60} 分钟没有归档读取的间隔，含范围边缘。暂停、服务未运行或未归档都可能留下空白，不能单凭此页确定原因。按日期筛选时，跨日间隔仍显示完整起止。</p><div id="quality-gaps"></div></section>`:''}`;
      paintDays();paintGaps();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function paintDays(){
      const el=node?.querySelector('#quality-days');if(!el||!data)return;
      const pages=Math.max(1,Math.ceil(data.days.length/7));dayPage=Math.min(dayPage,pages-1);
      el.innerHTML=`<div class="quality-days">${data.days.slice(dayPage*7,dayPage*7+7).map(day=>`<button data-quality-day="${day.date}" aria-pressed="${selected===day.date}"><strong>${day.date}</strong><span>${{future:'未来日期',missing:'无归档读取',observed:'有归档读取'}[day.status]} · ${day.reads} 次</span><span>有读取时段 ${day.read_slots} / ${day.elapsed_slots}</span><span>有时间推进时段 ${day.new_slots} / ${day.elapsed_slots}</span><span>新时间 ${day.counts.new} · 修订 ${day.counts.revision} · 重复 ${day.counts.repeat} · 异常 ${day.counts.invalid}</span></button>`).join('')}</div><div class="insight-pagination">${button('上一页质量日期','days-previous',dayPage===0)}<span>${dayPage+1} / ${pages}</span>${button('下一页质量日期','days-next',dayPage+1===pages)}</div>`;
    }
    function paintGaps(){
      const el=node?.querySelector('#quality-gaps');if(!el||!data)return;
      const lower=selected?Date.parse(selected+'T00:00:00+08:00'):null;
      const rows=data.gaps.filter(g=>lower===null||g.start<lower+86400000&&g.end>lower),pages=Math.max(1,Math.ceil(rows.length/12));gapPage=Math.min(gapPage,pages-1);
      node.querySelector('#quality-gap-heading').textContent=`读取间隔 · ${selected||'全范围'} · ${rows.length} 处`;
      el.innerHTML=rows.slice(gapPage*12,gapPage*12+12).map(g=>`<article class="rule-record"><div class="insight-heading"><h4>${gapLabels[g.kind]}</h4><span class="insight-badge">${number(g.duration_seconds/60)} 分钟</span></div><p>${esc(time(g.start))} → ${esc(time(g.end))}</p></article>`).join('')||'<p class="insight-empty">此筛选下没有超过阈值的读取间隔；不代表车况无缺失。</p>';
      if(rows.length)el.innerHTML+=`<div class="insight-pagination">${button('上一页读取间隔','gaps-previous',gapPage===0)}<span>${gapPage+1} / ${pages}</span>${button('下一页读取间隔','gaps-next',gapPage+1===pages)}</div>`;
    }
    function invalidate(){serial++;data=null;attempted=loading=false;error=selected='';dayPage=gapPage=0;paint();}
    async function load(){
      if(!owner||!start||!end)return;const identity=owner,token=++serial;attempted=loading=true;error='';paint();
      try{const result=await request('/api/insights/quality?start='+encodeURIComponent(start)+'&end='+encodeURIComponent(end));
        if(!valid(token,identity))return;if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=result;selected='';dayPage=gapPage=0;
      }catch(failure){if(valid(token,identity))error=failure.message;}
      finally{if(valid(token,identity)){loading=false;paint();}}
    }
    function mount(container){
      const changed=owner!==context(),remount=node!==container;node=container;
      if(changed){owner=context();data=null;attempted=loading=false;error=selected='';dayPage=gapPage=0;serial++;}
      if(changed||remount)paint();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;const el=event.target;
      if(event.type==='input'&&el.id==='quality-start'){if(start!==el.value){start=el.value;invalidate();}return true;}
      if(event.type==='input'&&el.id==='quality-end'){if(end!==el.value){end=el.value;invalidate();}return true;}
      if(event.type!=='click')return false;
      const day=el.closest('[data-quality-day]');if(day){selected=day.dataset.qualityDay;gapPage=0;paint();return true;}
      const target=el.closest('[data-quality]');if(!target||target.disabled)return false;const action=target.dataset.quality;
      if(action==='load')load();else if(action==='clear'){selected='';gapPage=0;paint();}
      else if(action==='snapshots')navigate('time',selected);
      else if(action==='days-previous'){dayPage--;paintDays();}else if(action==='days-next'){dayPage++;paintDays();}
      else if(action==='gaps-previous'){gapPage--;paintGaps();}else if(action==='gaps-next'){gapPage++;paintGaps();}
      return true;
    }
    return {mount,handle};
  }
  root.DataQualityPage={create};
})(window);
