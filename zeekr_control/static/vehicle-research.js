(function(root){
  'use strict';
  const labels={known:'已有解释',pending:'含义待核实',empty:'空值',invalid:'无效',missing:'未返回'};
  const modes={driving:'行驶',charging:'充电',parked:'停车',unknown:'场景未知'};
  const dispositions={analyzed:'已用于分析',insufficient:'样本不足',configuration:'配置背景'};
  const date=stamp=>new Date(stamp+8*3600000).toISOString().slice(0,10);
  const num=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:3}).format(value):'—';
  function create({getState,request,escape:esc,active,time,experiment,review}){
    let node=null,owner='',data=null,loading=false,serial=0,error='',attempted=false;
    let loadingTimer=null,loadingStarted=0,queuedPath=null,pendingFieldFocus=null;
    let start=date(Date.now()-6*86400000),end=date(Date.now()),path='',section='overview';
    let search='',group='',usage='',sort='activity',detailView='history',samplesOpen=false,rangeExpanded=false,page=0,pointPage=0,scene='cabin',showMissing=false,selected={before:null,after:null};
    const context=()=>getState()?.insights_context||'';
    const button=(text,action,extra='',disabled=false)=>`<button class="button secondary" data-research="${action}" ${extra} ${disabled?'disabled':''}>${text}</button>`;
    const stats=(value,caption,detail='')=>`<article class="research-stat"><strong>${num(value)}</strong><span>${caption}</span><small>${detail}</small></article>`;
    const fieldButton=f=>button(esc(f.name),'field',`data-path="${esc(f.path)}"`,loading);
    const filtered=()=>data.fields.filter(f=>(!group||f.group===group)&&(!usage||f.disposition===usage)&&`${f.name} ${f.path} ${f.group}`.toLowerCase().includes(search.toLowerCase()))
      .sort((a,b)=>{
        if(sort==='name')return a.name.localeCompare(b.name,'zh-CN');
        if(sort==='samples')return b.samples-a.samples||b.changes-a.changes;
        if(sort==='changes')return b.changes-a.changes||b.samples-a.samples;
        return Number(b.samples>0)-Number(a.samples>0)||b.changes-a.changes;
      });
    function preservingFocus(render){
      const focused=document.activeElement;
      const saved=node?.contains(focused)?{id:focused.id,data:{...focused.dataset}}:null;
      render();
      if(!saved)return;
      const target=[...node.querySelectorAll('button,input,select')].find(el=>saved.id?el.id===saved.id:
        Object.keys(saved.data).length&&Object.entries(saved.data).every(([key,value])=>el.dataset[key]===value));
      target?.focus({preventScroll:true});
    }
    const paint=()=>preservingFocus(paintContent);
    const paintBody=()=>preservingFocus(paintBodyContent);
    const paintRows=()=>preservingFocus(paintRowsContent);
    const paintPoints=()=>preservingFocus(paintPointsContent);
    function loadingStatus(){
      if(!loading||!active()||!node?.isConnected){clearInterval(loadingTimer);loadingTimer=null;return;}
      const el=node.querySelector('#research-loading');
      if(el)el.textContent=`正在整理字段与场景… 已用 ${Math.floor((Date.now()-loadingStarted)/1000)} 秒。较大范围可能需要数分钟，可先查看其他工具。`;
    }

    function paintContent(){
      if(!node?.isConnected||!active())return;
      node.innerHTML=`<header class="research-header"><div><h2>数据利用</h2><p>查覆盖，找变化，让已有观测成为证据。</p></div><span>本地归档 / 北京时间</span></header>
        <section class="card research-range" data-expanded="${rangeExpanded}"><div class="research-presets" aria-label="研究日期快捷范围">${[[1,'今日'],[7,'近 7 天'],[30,'近 30 天']].map(([days,label])=>button(label,'preset',`data-days="${days}" aria-pressed="${end===date(Date.now())&&start===date(Date.now()-(days-1)*86400000)}"`,!owner||loading)).join('')}${button('自选日期','range',`aria-expanded="${rangeExpanded}" aria-controls="research-range-inputs"`)}</div><div class="research-range-inputs" id="research-range-inputs"><label>研究开始日期<input id="research-start" type="date" value="${start}"></label><label>研究结束日期<input id="research-end" type="date" value="${end}"></label><button class="button" data-research="load" ${!owner||loading?'disabled':''}>分析本地数据</button></div>
        <p class="research-result-range">${data?`当前结果：${esc(data.start_date)} 至 ${esc(data.end_date)} · 截至 ${esc(time(data.as_of))}`:'选择日期查看归档，最多 31 天。'}<span id="research-range-draft"></span></p>${loading?'<p role="status" id="research-loading">正在整理字段与场景…</p>':''}${error?`<p class="notice error" role="alert">${esc(error)}</p>`:''}${!owner?'<p>等待当前账号的车辆缓存。</p>':''}</section>
        ${data?`<nav class="research-tabs" aria-label="数据研究视图">${[['overview','数据总览'],['scenes','场景分析'],['field','字段详情']].map(([key,label])=>`<button data-research="section" data-section="${key}" aria-pressed="${section===key}" ${key==='field'&&!data.detail?'disabled':''}>${label}</button>`).join('')}</nav><div id="research-body"></div>`:''}`;
      paintBody();rangeDraft();
      if(loading&&!loadingTimer)loadingTimer=setInterval(loadingStatus,1000);
      loadingStatus();
    }
    function rangeDraft(){
      const el=node?.querySelector('#research-range-draft');
      if(el)el.textContent=data&&(start!==data.start_date||end!==data.end_date)?'日期已修改，点击分析后更新结果。':'';
    }
    function paintBodyContent(){
      const el=node?.querySelector('#research-body');if(!el||!data)return;
      if(section==='field'&&data.detail){el.innerHTML=detail();paintPoints();return;}
      if(section==='scenes'){el.innerHTML=scenes();return;}
      el.innerHTML=`<section class="card research-overview"><div class="research-overview-facts"><span>公开目录 <b>${num(data.counts.catalog)}</b> 项</span><span>已返回 <b>${num(data.counts.returned_fields)}</b> 项</span><span>有效车辆时间 <b>${num(data.counts.samples)}</b> 个样本</span></div>
        <div class="research-coverage-filters">${Object.entries(dispositions).map(([key,label])=>{const count=data.fields.filter(f=>f.disposition===key).length;return `<button data-research="usage" data-usage="${key}" aria-pressed="${usage===key}" aria-label="${label} ${count} 项"><span>${label}</span><strong>${num(count)} <small>项</small></strong><i aria-hidden="true" style="--coverage:${100*count/(data.counts.catalog||1)}%"></i></button>`;}).join('')}</div>
        <details class="research-method"><summary>读取质量与统计口径 <span>${num(data.counts.reads)} 次归档读取</span></summary><p class="insight-note">新时间 ${data.quality.new} · 重复 ${data.quality.repeat} · 同时间修订 ${data.quality.revision} · 时间异常 ${data.quality.invalid}。分析使用有效时间样本，同时间取最后有效修订；有样本不等于解释已确认或连续覆盖。</p><p class="insight-note">未登记路径 ${data.counts.unmapped_is_lower_bound?'至少 ':''}${data.counts.unmapped_paths} 项，仅统计数量；原始路径和值留在私有归档。字段没有返回也保留在清单中。</p></details></section>
        <section class="card insight-panel research-directory"><div class="insight-heading"><h3>字段清单</h3><div class="research-directory-actions"><span id="research-field-count" class="research-result-count" role="status"></span>${button('清除字段筛选','clear-filters')}</div></div><div class="research-filters"><label class="research-search-label">搜索研究字段<input id="research-search" type="search" value="${esc(search)}" placeholder="字段名称或路径"></label><label>字段分类<select id="research-group"><option value="">全部分类</option>${data.groups.map(g=>`<option ${group===g?'selected':''}>${esc(g)}</option>`).join('')}</select></label><label>数据用途<select id="research-usage"><option value="">全部用途</option>${Object.entries(dispositions).map(([key,label])=>`<option value="${key}" ${usage===key?'selected':''}>${label}</option>`).join('')}</select></label><label>字段排序<select id="research-sort">${[['activity','优先有样本和变化'],['changes','原值变化最多'],['samples','有效样本最多'],['name','字段名称']].map(([key,label])=>`<option value="${key}" ${sort===key?'selected':''}>${label}</option>`).join('')}</select></label></div><div class="research-filter-status"><span id="research-filter-summary"></span></div><div id="research-fields"></div></section>
        <section class="card insight-panel"><details><summary>数据来源与已有用途 · ${data.sources.length} 类</summary><div class="research-source-list">${data.sources.map(s=>`<article><b>${esc(s.name)} · ${s.count}</b><span>${esc(s.use)}</span><small>${esc(s.scope)}</small></article>`).join('')}</div></details></section>`;
      paintRows();
    }
    function paintRowsContent(){
      const el=node?.querySelector('#research-fields');if(!el)return;
      const rows=filtered(),pages=Math.max(1,Math.ceil(rows.length/12));page=Math.min(page,pages-1);
      node.querySelector('#research-field-count').textContent=`${rows.length} / ${data.counts.catalog} 项`;
      node.querySelector('#research-filter-summary').textContent=search||group||usage?'筛选中 · '+[search,group,dispositions[usage]].filter(Boolean).join(' / '):'';
      node.querySelector('.research-filter-status').hidden=!(search||group||usage);
      node.querySelectorAll('[data-research="usage"]').forEach(el=>el.setAttribute('aria-pressed',String(usage===el.dataset.usage)));
      const visible=rows.slice(page*12,page*12+12);
      el.innerHTML=rows.length?`<table class="research-field-table"><caption class="research-sr-only">字段清单：返回率按归档读取统计；样本按有效字段时间统计。</caption><thead><tr><th scope="col">字段 / 用途</th><th scope="col">返回率</th><th scope="col">有效样本</th><th scope="col">原值变化</th></tr></thead><tbody>${visible.map(f=>{const returned=data.counts.reads-f.read_counts.missing,rate=data.counts.reads?Math.round(returned/data.counts.reads*1000)/10:null;return `<tr><th scope="row">${fieldButton(f)}<span class="research-field-meta">${esc(f.group)} / ${dispositions[f.disposition]}</span></th><td data-label="返回率"><strong>${rate===null?'—':num(rate)+'%'}</strong><small>${num(returned)} / ${num(data.counts.reads)} 次读取</small></td><td data-label="有效样本" data-field-samples="${f.samples}"><strong>${num(f.samples)}</strong><small>个有效字段时间</small></td><td data-label="原值变化"><strong>${num(f.changes)}</strong><small>次观测变化</small></td></tr>`;}).join('')}</tbody></table><div class="insight-pagination">${button('上一页字段','previous','',page===0)}<span>第 ${page+1} / ${pages} 页</span>${button('下一页字段','next','',page+1===pages)}</div>`:'<p class="insight-empty">没有匹配字段。清除筛选可查看完整目录。</p>';
    }
    function numberSummary(s){return `${num(s.min)} ～ ${num(s.max)} · 均值 ${num(s.mean)} · ${s.count} 个数值`;}
    function plot(points){
      const valid=points.filter(p=>Number.isFinite(p.number)&&Number.isFinite(p.time));
      if(!valid.length)return '<p class="insight-empty">没有可绘制的有效数值点；下方仍可查看状态和原值。</p>';
      const lo=Math.min(...valid.map(p=>p.number)),hi=Math.max(...valid.map(p=>p.number));
      const first=Math.min(...valid.map(p=>p.time)),last=Math.max(...valid.map(p=>p.time));
      return `<figure class="research-chart"><figcaption>离散观测 · ${num(lo)} ～ ${num(hi)}</figcaption><div class="research-plot"><div class="research-y-axis" aria-hidden="true">${(hi===lo?[null,lo,null]:[hi,(hi+lo)/2,lo]).map(v=>`<span>${v===null?'':num(v)}</span>`).join('')}</div><svg viewBox="0 0 730 190" preserveAspectRatio="none" role="img" aria-label="数值历史散点图，点之间不连线"><path d="M5 15 V170 H725" fill="none" stroke="currentColor" opacity=".3"/>${[25,92.5,160].map(y=>`<path class="research-gridline" d="M5 ${y} H725"/>`).join('')}${valid.map(p=>`<circle cx="${5+715*(p.time-first)/(last-first||1)}" cy="${hi===lo?92.5:160-135*(p.number-lo)/(hi-lo)}" r="2" fill="currentColor" stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke"><title>${esc(time(p.time))} · ${num(p.number)}</title></circle>`).join('')}</svg></div><div class="research-axis"><span>${esc(time(first))}</span><span>${esc(time(last))}</span></div></figure>`;
    }
    function detail(){
      const d=data.detail,f=d.field;
      return `${button('返回字段清单','back')}<section class="card insight-panel research-detail-head"><div class="insight-heading"><div><h3>${esc(f.name)}</h3><p>${esc(f.reason)}</p></div>${button('打开参数字典','dictionary')}</div><div class="research-detail-stats">${stats(f.samples,'有效字段时间样本')}${stats(f.changes,'原值变化次数')}${stats(f.distinct,'不同原值',f.distinct_is_lower_bound?'至少，超过 256 项':'区分原始类型')}</div><details class="research-method"><summary>字段定义与读取质量</summary><small class="research-path">${esc(f.path)}</small><p class="insight-note">${esc(f.applicability)}<br>${esc(f.note)}</p><p class="insight-note">首次返回 ${esc(time(f.first_returned))} · 最后返回 ${esc(time(f.last_returned))}<br>时间缺失、陈旧或重复：${num(f.time_excluded)} 次</p>${f.current?`<p>当前配置：${esc(f.current.value)} · 原值 ${esc(f.current.raw)} · 更新时间未提供</p>`:''}<div class="research-status-counts">${Object.entries(f.read_counts).map(([key,n])=>`<span>${labels[key]} <b>${n}</b></span>`).join('')}</div><p class="insight-note">五类计数以归档读取为分母；有效样本另做时间去重。</p></details></section>
        <nav class="research-detail-tabs" aria-label="字段详情分区">${[['history','历史取证'],['distribution','分布与场景'],['evidence','实验与核实']].map(([key,label])=>`<button data-research="detail-view" data-view="${key}" aria-pressed="${detailView===key}">${label}</button>`).join('')}</nav>
        ${detailView==='history'?history(d,f):detailView==='distribution'?distribution(d,f):evidence()}`;
    }
    function history(d,f){
      const unit=f.pending_samples?'原值，单位尚未确认':f.unit;
      return `<section class="card insight-panel"><div class="insight-heading"><h3>数值历史</h3><span class="insight-note">${esc(unit)}</span></div><p class="insight-note">${numberSummary(f.numeric)}</p>${plot(d.points)}<p class="insight-note">${d.point_count} 条规范车辆时间观测，展示 ${d.points.length} 条${d.point_count>d.points.length?'（分桶保留端点与数值极值）':''}。点之间不连线，未知时段不补值。</p><details class="research-method"><summary>时间间隔、延迟与变化速率</summary><p class="insight-note">有效字段时间间隔（不跨 10 分钟缺口）：${numberSummary(f.cadence_seconds)} 秒<br>采集读取时的数据延迟：${numberSummary(f.delay_seconds)} 秒${f.numeric.count?'<br>相邻有效观测的每分钟变化：'+numberSummary(f.rate_per_minute):''}</p></details>
        <div class="research-sample-toggle">${button('选择前后样本','samples',`aria-expanded="${samplesOpen}" aria-controls="research-samples"`)}<span>带入实验室，记录实际动作与证据</span></div><div id="research-samples" ${samplesOpen?'':'hidden'}><div class="research-selection"><span>前样本：${selected.before?esc(time(selected.before.observed_at)):'未选'}</span><span>后样本：${selected.after?esc(time(selected.after.observed_at)):'未选'}</span>${button('用所选样本建实验','experiment','',!selected.before||!selected.after||selected.before.key===selected.after.key||selected.before.observed_at>selected.after.observed_at)}</div><div id="research-points"></div></div></section>
        <section class="card insight-panel"><details><summary>变化边界 · ${d.transitions.length} 条</summary><p class="insight-note">变化发生在两次观测之间，不能确定精确时刻；最多列出前 100 个原值或状态边界。</p><div class="research-distribution">${d.transitions.map(t=>`<article><span>${esc(t.before_raw)} → ${esc(t.after_raw)}</span><small>${esc(time(t.from_time))} 至 ${esc(time(t.to_time))}${t.gap?' · 有缺样或时间异常':''}${t.display_limited?' · 显示已简化，完整原值有变化':''}</small></article>`).join('')||'<p>尚未观察到变化边界。</p>'}</div></details></section>`;
    }
    function distribution(d,f){return `<section class="card insight-panel"><h3>原值分布与场景</h3><p class="insight-note">样本计数，不是时长占比。仅展示最先遇到的 20 种原值；其他原值 ${f.distribution_other} 个样本。</p><div class="research-distribution">${f.distribution.map(v=>`<article><code>${esc(v.raw)}</code><span>${v.count} 次 · ${labels[v.status]} · ${esc(v.value)}</span></article>`).join('')||'<p>没有有效样本。</p>'}</div>${d.histogram.length?`<h4>数值分布</h4><div class="research-histogram">${d.histogram.map(b=>`<div><span>${num(b.min)}–${num(b.max)}</span><meter min="0" max="${Math.max(...d.histogram.map(h=>h.count),1)}" value="${b.count}">${b.count}</meter><b>${b.count}</b></div>`).join('')}</div>`:''}<div class="research-source-list">${Object.entries(f.scenarios).map(([key,s])=>`<article><b>${modes[key]} · ${s.samples} 个样本</b><span>${numberSummary(s.numeric)}</span></article>`).join('')}</div></section>`;}
    function evidence(){return `<section class="card insight-panel"><h3>实验与人工核实</h3><p class="insight-note">实验保留证据，字典保存人工解释；不会自动改变解码或通知规则。</p>${data.experiments.map(r=>`<article class="research-evidence"><span>${esc(r.title)} · ${esc(time(r.action_at))}</span>${button('回看关联实验','saved-experiment',`data-id="${esc(r.id)}"`)}</article>`).join('')||'<p>这个字段暂无关联实验。</p>'}${data.reviews.map(r=>`<article><b>${esc(r.raw)} · ${esc(r.meaning||r.note||'未填写解释')}</b><p class="insight-note">人工记录：${esc({confirmed:'已确认',question:'有疑问',na:'不适用'}[r.status])}${r.evidence?' · 证据：'+esc(r.evidence.title):''}</p></article>`).join('')}</section>`;}
    function paintPointsContent(){
      const el=node?.querySelector('#research-points');if(!el||!data.detail)return;
      const points=data.detail.points,pages=Math.max(1,Math.ceil(points.length/6));pointPage=Math.min(pointPage,pages-1);
      el.innerHTML=`<div class="research-point-list">${points.slice(pointPage*6,pointPage*6+6).map(p=>`<article><div><b>${esc(p.raw)}</b> · ${labels[p.status]}${!p.usable?' · 未计入有效字段样本':''}<small>字段 ${esc(time(p.time))} · ${esc(p.time_source)}</small><small>采集 ${esc(time(p.observed_at))} · ${modes[p.scenario]} · 读取延迟 ${num(p.delay_seconds)} 秒${p.gap_before?' · 前有缺口或时间异常':''}</small></div><div>${button('选作前样本','pick',`data-side="before" data-key="${esc(p.key)}" aria-pressed="${selected.before?.key===p.key}"`)}${button('选作后样本','pick',`data-side="after" data-key="${esc(p.key)}" aria-pressed="${selected.after?.key===p.key}"`)}</div></article>`).join('')||'<p>当前范围没有历史观测。</p>'}</div><div class="insight-pagination">${button('上一页观测','points-previous','',pointPage===0)}<span>${pointPage+1} / ${pages}</span>${button('下一页观测','points-next','',pointPage+1===pages)}</div>`;
    }
    function scenes(){
      const selectedScene=data.scenes.find(s=>s.id===scene)||data.scenes[0];
      const rows=data.fields.filter(f=>selectedScene.paths.includes(f.path)&&(showMissing||f.samples>0));
      return `<section class="card insight-panel"><h3>按用车场景查看数据</h3><div class="research-scene-nav">${data.scenes.map(s=>`<button class="button secondary" data-research="scene" data-scene="${s.id}" aria-pressed="${scene===s.id}"><b>${s.name}</b><small>${s.available_fields} / ${s.total_fields} 项有样本</small></button>`).join('')}</div><p class="insight-note">场景由已有有效车速、动力与充电组合识别；条件不足归入未知。共同变化是线索，不能直接推断因果或健康状况。</p></section>
        <section class="card insight-panel"><div class="insight-heading"><h3>${selectedScene.name}</h3>${button(showMissing?'仅看有样本字段':'显示样本不足字段','missing')}</div>${selectedScene.paired_delta?`<p>同次有效内外温差（车内减车外，°C）：${numberSummary(selectedScene.paired_delta)}</p>`:''}${selectedScene.conditions?`<h4>相近车外条件下的座舱观测</h4><p class="insight-note">按车外温度区间、车辆场景和空调字段原值分组，原值不直接解释为开关；均值按观测加权，不能据此认定制冷效果或耗电原因。最多 100 组，其他组合 ${selectedScene.conditions_other} 次。</p><div class="research-scene-fields">${selectedScene.conditions.map(c=>`<article><b>${esc(c.name)} · 原值 ${esc(c.raw)}</b><span>${c.outside_band} · ${modes[c.scenario]}</span><small>车内均值 ${num(c.inside.mean)}°C · 车外均值 ${num(c.outside.mean)}°C · ${c.inside.count} 个样本</small><small>内外温差：${numberSummary(c.delta)} °C</small></article>`).join('')||'<p>需要同次有效内外温度与空调状态；当前范围样本不足。</p>'}</div>`:''}${selectedScene.wheel_spread?`<p>同次四轮胎压最大差（kPa）：${numberSummary(selectedScene.wheel_spread)}</p>`:''}<p class="insight-note">温度使用独立更新时间；四轮差异要求同次快照四轮都有有效值。数值含义待核实时只比较原值。</p><div class="research-scene-fields">${rows.map(f=>`<article>${fieldButton(f)}<span>${f.samples} 个样本 · ${f.changes} 次变化</span><small>${f.numeric.count?numberSummary(f.numeric):esc(f.reason)}${f.pending_samples?' · 原值含义待核实':''}</small><small>${Object.entries(f.scenarios).map(([key,s])=>modes[key]+' '+s.samples).join(' · ')}</small></article>`).join('')||'<p>本范围暂没有可用字段样本；可展开缺样字段，或扩大日期范围。</p>'}</div></section>${scene==='journeys'?events():''}`;
    }
    function events(){
      const e=data.event_conditions;
      return `<section class="card insight-panel"><h3>行程与充电的条件比较</h3><p class="insight-note">按结束日期计入 ${e.total} 条可见事件。按车外温度、起始电量、充电方式分别分组，各维度不能相加。只用完整、未跨出选择范围的事件作电量估算比较；行程每百公里估算另要求至少 10 km、SOC 下降至少 3%。温度为事件内有效观测均值，不是全程均温。</p><div class="research-scene-fields">${e.groups.map(g=>`<article><b>${g.kind==='trip_end'?'行程':'充电'} · ${esc(g.label)}</b><span>${g.events} 条事件 · ${g.usable_events} 条可估算</span><small>单次估算电量均值 ${num(g.energy.mean)} kWh · ${g.energy.count} 条</small>${g.kind==='trip_end'?`<small>单次每百公里估算均值 ${num(g.consumption.mean)} kWh/100km · ${g.consumption.count} 条</small>`:''}</article>`).join('')||'<p>没有可用于比较的结束事件。</p>'}</div><details><summary>核对关联样本 · 前 ${e.events.length} 条事件</summary><div class="research-source-list">${e.events.map(r=>`<article><b>${r.kind==='trip_end'?'行程':'充电'} · ${esc(time(r.end_time))}</b><span>${r.observed_samples} 个归档样本 · ${r.temperature_samples} 个有效温度样本</span><small>车外观测均值 ${num(r.outside_mean)}°C${r.partial?' · 事件不完整':''}${r.range_partial?' · 起点不在范围内或未知':''}</small></article>`).join('')}</div></details></section>`;
    }
    async function load(nextPath=path){
      if(!owner)return;
      if(loading){queuedPath=nextPath;return;}
      const identity=owner,token=++serial;loading=true;loadingStarted=Date.now();attempted=true;error='';path=nextPath;paint();
      try{
        const result=await request('/api/insights/research?start='+encodeURIComponent(start)+'&end='+encodeURIComponent(end)+'&path='+encodeURIComponent(path),undefined,300000);
        if(token!==serial||identity!==owner||context()!==identity)return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        const differentField=data?.detail?.field.path!==result.detail?.field.path;
        data=result;selected={before:null,after:null};pointPage=0;if(differentField){detailView='history';samplesOpen=false;}
      }catch(failure){if(token===serial&&context()===identity)error=failure.message;}
      finally{
        if(token===serial&&context()===identity){
          loading=false;paint();
          const next=queuedPath;queuedPath=null;
          if(next!==null&&next!==path)load(next);
          else if(!error&&pendingFieldFocus===data?.detail?.field.path){
            pendingFieldFocus=null;
            if(section==='field'&&active()&&node?.isConnected){
              const entry=node.querySelector('[data-research=back]');
              entry?.focus({preventScroll:true});entry?.scrollIntoView({block:'start'});
            }
          }
        }
      }
    }
    function mount(container){
      const changed=owner!==context(),remount=node!==container;node=container;
      if(changed){owner=context();data=null;serial++;loading=attempted=false;queuedPath=pendingFieldFocus=null;error='';path='';section='overview';search=group=usage='';sort='activity';detailView='history';samplesOpen=false;rangeExpanded=false;page=pointPage=0;selected={before:null,after:null};}
      if(changed||remount)paint();if(owner&&!attempted&&!loading)queueMicrotask(()=>{if(owner&&!attempted&&!loading)load();});
    }
    function openField(target){section='field';pendingFieldFocus=target;load(target);}
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;
      const el=event.target;
      if(event.type==='input'){
        if(el.id==='research-start'){start=el.value;rangeDraft();return true;}
        if(el.id==='research-end'){end=el.value;rangeDraft();return true;}
        if(el.id==='research-search'){search=el.value;page=0;paintRows();return true;}
      }
      if(event.type==='change'&&['research-group','research-usage','research-sort'].includes(el.id)){if(el.id==='research-group')group=el.value;else if(el.id==='research-sort')sort=el.value;else usage=el.value;page=0;paintRows();return true;}
      if(event.type!=='click')return false;
      const target=el.closest('[data-research]');if(!target||target.disabled)return false;
      const action=target.dataset.research;
      if(action==='load')load();
      else if(action==='range'){rangeExpanded=!rangeExpanded;paint();}
      else if(action==='preset'){const now=Date.now();end=date(now);start=date(now-(Number(target.dataset.days)-1)*86400000);load();}
      else if(action==='usage'){usage=usage===target.dataset.usage?'':target.dataset.usage;page=0;node.querySelector('#research-usage').value=usage;paintRows();}
      else if(action==='clear-filters'){search=group=usage='';sort='activity';page=0;paintBody();node.querySelector('#research-search').focus({preventScroll:true});}
      else if(action==='back'){section='overview';paint();const field=[...node.querySelectorAll('[data-research=field]')].find(el=>el.dataset.path===path);field?.focus();}
      else if(action==='detail-view'){detailView=target.dataset.view;paintBody();}
      else if(action==='samples'){samplesOpen=!samplesOpen;paintBody();}
      else if(action==='field')openField(target.dataset.path);
      else if(action==='section'){section=target.dataset.section;if(section!=='field')pendingFieldFocus=null;paint();}
      else if(action==='scene'){scene=target.dataset.scene;paintBody();}
      else if(action==='missing'){showMissing=!showMissing;paintBody();}
      else if(action==='previous'||action==='next'){page+=action==='next'?1:-1;paintRows();}
      else if(action==='points-previous'||action==='points-next'){pointPage+=action==='points-next'?1:-1;paintPoints();}
      else if(action==='pick'){selected[target.dataset.side]=data.detail.points.find(p=>p.key===target.dataset.key);paintBody();}
      else if(action==='experiment')experiment({path:data.detail.field.path,name:data.detail.field.name,...selected});
      else if(action==='saved-experiment')experiment({id:target.dataset.id});
      else if(action==='dictionary')review(data.detail.field);
      return true;
    }
    return {mount,handle,openField};
  }
  root.VehicleResearchPage={create};
})(window);
