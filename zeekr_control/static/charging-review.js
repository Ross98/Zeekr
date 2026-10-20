(function(root){
  'use strict';
  const dateAt=t=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(t));
  const clock=t=>Number.isFinite(t)?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(t)):'起点未知';
  const number=(n,digits=1)=>Number.isFinite(n)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:digits}).format(n):'未知';
  const money=n=>Number.isFinite(n)?(n/100).toFixed(2)+' 元':'费用待补';
  const modes={ac:'交流充电（AC）',dc:'直流充电（DC）',unknown:'类型未知'};
  const duration=n=>{if(!Number.isFinite(n))return '时长未知';if(n>0&&n<60)return '<1 分钟';const m=Math.round(n/60),h=Math.floor(m/60);return (h?h+' 小时 ':'')+(m%60||!h?(m%60)+' 分钟':'');};
  function create({getState,request,escape:esc,active,openRecord,openLedger}){
    let node=null,owner='',month=dateAt(Date.now()).slice(0,7),data=null,loading=false,error='',expanded='',pending=false,serial=0,controller=null,revision='',loadedMonth='',attempted=false;
    const context=()=>getState()?.insights_context||'';
    const valid=token=>token===serial&&owner===context()&&active();
    const button=(label,action,attrs='')=>`<button type="button" class="cursor-interaction cr-action" data-review="${action}" ${attrs}>${label}</button>`;
    function battery(e){
      const valid=n=>Number.isFinite(n)&&n>=0&&n<=100;
      const known=valid(e.start_soc)&&valid(e.end_soc)&&e.end_soc>=e.start_soc&&e.energy_soc_delta!=null;
      const marker=(n,side)=>valid(n)?`<span class="cr-soc" style="left:${n}%;transform:translateX(${n===0?'0':n===100?'-100%':'-50%'})">${number(n)}%</span>`:`<span class="cr-soc" style="${side==='start'?'left:0':'right:0'}">${side==='start'?'起点':'终点'}未知</span>`;
      return `<div class="cr-battery">${marker(e.start_soc,'start')}${marker(e.end_soc,'end')}<div class="cr-bar" role="img" aria-label="${known?`历史电量 ${e.start_soc}% 至 ${e.end_soc}%，补能 ${number(e.end_soc-e.start_soc)} 个百分点`:'历史电量区间未知'}">${known?`<span class="cr-before" style="width:${e.start_soc}%"></span><span class="cr-added" style="width:${e.end_soc-e.start_soc}%"></span>`:''}</div><span class="cr-delta" style="left:${known?Math.max(22,Math.min(78,(e.start_soc+e.end_soc)/2)):50}%">${known?`补能 +${number(e.end_soc-e.start_soc)} 个百分点`:'补能幅度未知'}</span></div>`;
    }
    function analysis(){
      const s=data.summary,a=data.analysis,c=data.comparison,d=data.intervals.summary;
      const groups=data.groups.filter(g=>g.actual_cents!=null);
      const total=s.actual_cents||0;
      const change=Number.isFinite(c.change_percent)?(c.change_percent>0?'+':'')+number(c.change_percent,1):'—';
      return `<section class="cr-analysis" aria-label="本月充电分析"><div class="cr-analysis-head"><h3>充电花费构成</h3><span class="cr-muted">按已知费用 · ${s.pending_count} 次待补账未计入</span></div>${groups.length?`<div class="cr-share-labels" style="grid-template-columns:${groups.map(g=>`minmax(180px,${Math.max(1,g.actual_cents)}fr)`).join(' ')}">${groups.map(g=>`<div class="cr-share-label" data-cost-mode="${g.mode}"><div class="cr-share-name">${modes[g.mode]}<span>${Number.isFinite(g.share_percent)?number(g.share_percent)+'%':'占比未知'}</span></div><strong>${money(g.actual_cents)}</strong></div>`).join('')}</div><svg class="cr-share-guides" aria-hidden="true"></svg><div class="cr-share" role="img" aria-label="${esc(groups.map(g=>modes[g.mode]+' '+money(g.actual_cents)).join('；'))}">${total>0?groups.map(g=>`<span data-share-mode="${g.mode}" class="cr-share-${g.mode}" style="width:${Math.max(0,g.actual_cents/total*100)}%"></span>`).join(''):''}</div>`:'<p class="cr-muted">暂无已填费用，不能计算金额占比。</p>'}<div class="cr-analysis-metrics"><div><span>实际综合电价</span><strong class="cr-analysis-value">${a.unit_price_cents_per_kwh==null?'—':number(a.unit_price_cents_per_kwh/100,2)} <small>元/kWh</small></strong><p class="cr-muted">${a.metered_samples} 次费用与电表电量匹配${a.metered_kwh!=null?' · '+number(a.metered_kwh)+' kWh':''}</p></div><div><span>较上月${data.window.end>data.as_of?'同期':'整月'} · 已知费用</span><strong class="cr-analysis-value">${change}<small>${c.change_percent==null?'':'%'}</small></strong><p class="cr-muted">${c.change_cents==null?'同期费用依据不足':(c.change_cents>0?'+':'')+money(c.change_cents)}${s.pending_count||c.previous_pending_count?' · 存在待补账':''}</p><p class="cr-muted">${esc(data.window.start_date)} 至 ${esc(c.current_end_date||'未来日期')}<br>对比 ${esc(c.previous_start_date)} 至 ${esc(c.previous_end_date||'—')}</p></div><div data-interval-metric><span>区间综合电耗 · SOC 估算</span><strong class="cr-analysis-value">${d.kwh_per_100km==null?'样本不足':number(d.kwh_per_100km,2)}${d.kwh_per_100km==null?'':' <small>kWh/100 km</small>'}</strong><p class="cr-muted">${d.kwh_per_100km==null?'区间依据不足，暂无法估算':number(d.distance_km)+' km · '+number(d.estimated_kwh)+' kWh'}</p><p class="cr-muted">纳入 ${d.valid_count} / ${d.interval_count} 个区间 · 含行驶、停车及空调用电</p><p class="cr-muted">${d.cents_per_100km==null?'参考电费依据不足':`参考电费 ${number(d.cents_per_100km/100,2)} 元/100 km · ${d.priced_count} 个区间 / ${number(d.priced_distance_km)} km`}</p></div></div><details><summary>计算依据与数据范围</summary><p>综合电价使用同一批账单费用与电表电量，不使用 SOC 估算电量计算桩端电价。类型优先使用已保存的手动修正，否则以历史 AC／DC 记录为准，不能确认的单列未知，不按地点判断。</p><p>当月比较上月相同已过时段，已结束月份比较整月；费用未填不按零计算。上期为 0 或缺少记录时，不计算变化百分比。</p><p>综合电耗使用上次充电结束 SOC 到下次充电开始 SOC 的差，乘当时保存的电池容量，再除以两端里程表之差；包含这段时间内行驶、停车及空调用电，属于电池侧 SOC 估算，不含充电损耗。整数 SOC 存在误差；未被采集到的充电也可能影响结果。</p><p>区间至少 ${data.intervals.rules.min_distance_km} km、SOC 下降至少 ${data.intervals.rules.min_soc_drop} 个百分点；端点缺失、首次观测已在充电、容量或解码版本变化、里程回退、SOC 回升及中间充电记录不完整时不纳入。月份按后一次充电结束月归档，跨月区间保留完整；汇总使用总耗电量除以总里程，不平均单个区间电耗。</p><p>参考电费按各区间前一次充电账单的实际费用 ÷ 电表电量估算；不代表电池存量的精确成本，不含充电损耗。缺少费用或电表电量的区间仅计算电耗，费用汇总只使用有价格的区间及其里程。</p><p>最多回看 180 天寻找前次充电。${data.history_quality.unreadable_or_undated?'有 '+data.history_quality.unreadable_or_undated+' 条历史无法归期或读取。':''}充电费用按关联充电结束日归期，与账单支付月份可能不同；SOC 补能与桩端电表电量口径分开。</p></details>${intervalDetails()}</section>`;
    }
    function intervalDetails(){
      const i=data.intervals;
      const reasons={missing_previous:'缺少前一次充电记录',hidden_charge:'相邻充电记录已隐藏，不能跨过计算',undated_charge:'有无法归期的充电记录',unclosed_charge:'中间存在未配对的充电开始记录',overlap:'充电时间交叠或边界缺失',late_start:'下次充电首次观测时已在充电',decoder_changed:'解码版本变化',missing_endpoint:'缺少有效的历史端点 SOC 或里程',missing_capacity:'缺少历史电池容量',capacity_changed:'两端电池容量配置不同',odometer_reset:'里程表回退',odometer_jump:'区间里程与时间明显不符',no_distance:'区间没有可用行驶里程',soc_increase:'区间 SOC 回升，可能存在未记录补能',soc_resolution:'SOC 变化太小，无法可靠估算',short_distance:'区间里程太短'};
      return `<details class="cr-intervals" data-detail="charging-intervals"><summary>两次充电之间的综合电耗 · ${i.summary.valid_count} 个有效区间</summary><p class="cr-muted">按后一次充电结束月份归档；跨月区间完整计入，不拆分。参考电费按前次账单单价估算。</p>${i.open_interval?`<p class="cr-muted">自 ${esc(clock(i.open_interval.start_time))} 起的区间尚无下一次已结束充电记录，等待闭合。</p>`:''}${i.records.length?`<div class="cr-interval-list">${i.records.map(r=>`<article class="cr-interval" data-charge-interval="${esc(r.id)}"><div><strong>${esc(clock(r.start_time))} 至 ${esc(clock(r.end_time))}${r.cross_month?' · 跨月':''}</strong><p class="cr-muted">${r.reason?esc(reasons[r.reason]||'依据不足'):`SOC ${number(r.start_soc)}% 至 ${number(r.end_soc)}% · ${number(r.distance_km)} km · ${number(r.estimated_kwh)} kWh`}</p></div><div>${r.reason?'<strong>未纳入</strong>':`<strong>${number(r.kwh_per_100km,2)} <small>kWh/100 km</small></strong><p class="cr-muted">${r.estimated_cents==null?'参考电费依据不足':'参考电费 '+money(r.estimated_cents)}</p>`}</div></article>`).join('')}</div>`:'<p class="cr-muted">该月暂无可归期的闭合区间。</p>'}${i.quality.undated_charge_count?'<p class="cr-muted">存在无法读取或归期的充电记录，暂不计算区间电耗。</p>':''}</details>`;
    }
    function record(e){
      const day=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',day:'numeric'}).format(new Date(e.end_time));
      const weekday=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',weekday:'short'}).format(new Date(e.end_time));
      const open=expanded===e.id,bill=e.bill;
      return `<article class="cr-event" data-review-record="${esc(e.id)}"><div class="cr-date"><strong>${esc(day.replace('日',''))}</strong><span class="cr-muted">${Number(dateAt(e.end_time).slice(5,7))} 月 · ${esc(weekday)}</span></div><div class="cr-content"><div class="cr-line"><span class="cr-place">${esc(e.place_label)}${e.place_reference?' · 参考位置':''}</span><span class="cr-money">${money(bill?.actual_cents)}</span></div><div class="cr-observed"><span>${esc(clock(e.start_time))}–${esc(clock(e.end_time))}</span><span>${duration(e.duration_seconds)}</span><span>${modes[e.mode]}${e.mode_source==='manual'?' · 手动修正':''}${e.partial?' · 部分记录':''}</span></div><div class="cr-energy">${battery(e)}<div class="cr-kwh"><strong>${number(e.estimated_kwh)}</strong> <small>${e.estimated_kwh==null?'电量估算不足':'kWh · SOC 估算'}</small></div>${button(open?'收起':'展开','expand',`data-review-expand="${esc(e.id)}" aria-expanded="${open}" aria-controls="review-detail-${esc(e.id)}"`)}</div>${open?`<section class="cr-detail" id="review-detail-${esc(e.id)}"><div><span class="cr-muted">账单电表电量</span><strong>${bill?.metered_kwh==null?'未填写':number(bill.metered_kwh)+' kWh'}</strong></div><div><span class="cr-muted">实际费用</span><strong>${money(bill?.actual_cents)}</strong></div><div><span class="cr-muted">历史地点</span><strong>${esc(e.place_label)}</strong></div><div><span class="cr-muted">记录完整性</span><strong>${e.partial?'部分记录':'已结束记录'}</strong></div><p class="cr-quality">${e.partial?'实际起点可能更早，只展示已观测片段。':'起止时间来自历史采集，不代表精确插拔枪时间。'}电量估算使用当时保存的容量；没有地点依据时不使用当前位置补填。</p><div class="cr-detail-actions">${button('查看充电曲线','curve',`data-id="${esc(e.id)}"`)}${button(bill?'打开账单':'补充充电账单','ledger',`data-id="${esc(e.id)}"`)}</div></section>`:''}</div></article>`;
    }
    function guides(){
      const svg=node?.querySelector('.cr-share-guides'),bar=node?.querySelector('.cr-share');if(!svg||!bar)return;
      const bounds=svg.getBoundingClientRect();svg.setAttribute('viewBox',`0 0 ${Math.max(1,bounds.width)} 14`);
      svg.innerHTML=[...node.querySelectorAll('[data-cost-mode]')].map(label=>{
        const segment=bar.querySelector(`[data-share-mode="${label.dataset.costMode}"]`);if(!segment)return '';
        const a=label.getBoundingClientRect(),b=segment.getBoundingClientRect();
        return `<path d="M${a.x+a.width/2-bounds.x} 0 L${b.x+b.width/2-bounds.x} 14"/>`;
      }).join('');
    }
    function paint(){if(!node?.isConnected||!active())return;return root.RefreshView?root.RefreshView.preserve(node,draw):draw();}
    function draw(){
      if(root.deferDateRender?.(paint))return;
      const s=data?.summary;
      node.dataset.loadedMonth=data?loadedMonth:'';
      node.innerHTML=`<div class="cr-toolbar"><h3>充电回顾</h3><div class="cr-month-controls"><label class="cr-muted" for="charging-review-month">月份</label><input id="charging-review-month" type="month" value="${esc(month)}" aria-label="充电月份">${button('本月','today')}${button('刷新充电回顾','load',loading?'aria-busy="true"':'')}</div></div>${error?`<p role="alert" class="notice error">${esc(error)}</p>`:''}${loading?'<p class="cr-muted" role="status">正在读取本地充电记录与账单…</p>':''}<section class="cr-totals" aria-label="本月充电汇总">${[
        ['已知充电花费',s?.actual_cents==null?'—':(s.actual_cents/100).toFixed(2)+' <small>元</small>',s?`${s.known_count} 次已记账 ${button(pending?'显示全部':s.pending_count+' 次待补账','pending',`aria-pressed="${pending}"`)}`:'等待本地记录'],
        ['累计补能 · SOC 估算',s?.estimated_kwh==null?'—':number(s.estimated_kwh)+' <small>kWh</small>',s?`${s.energy_samples} / ${s.charge_count} 次可估算 · 含 ${s.partial_count} 次片段`:''],
        ['充电次数',s?s.charge_count+' <small>次</small>':'—',s?`${s.charge_count-s.partial_count} 次完整 · ${s.partial_count} 次片段`:'']
      ].map(([label,value,note])=>`<div class="cr-total"><span class="cr-muted">${label}</span><strong>${value}</strong><span class="cr-muted">${note}</span></div>`).join('')}</section>${data?analysis():''}<div class="cr-records-heading"><h3>本月充电记录</h3><span class="cr-muted">按结束时间 · 新记录在前</span></div>${data?.records.length?`<section class="cr-timeline" aria-label="本月充电时间轴">${data.records.filter(e=>!pending||e.bill?.actual_cents==null).map(record).join('')||'<p class="cr-empty">没有待补账记录。</p>'}</section>`:`<p class="cr-empty">${loading?'等待本月记录…':data?'该月暂无已结束充电记录；不代表车辆没有充电。':'等待当前账号车辆缓存。'}</p>`}<div class="cr-legend"><span><i></i>充电前 SOC</span><span><i class="cr-green"></i>本次补入</span><span>条形展示历史电量变化</span></div>${data?`<p class="cr-muted">数据截至 ${esc(clock(data.as_of))} · 仅读取本地记录，不请求车辆。</p>`:''}`;
      guides();
    }
    async function load(){
      if(!active()||!owner||!/^20\d{2}-(0[1-9]|1[0-2])$/.test(month))return;
      controller?.abort();controller=new AbortController();const token=++serial,target=month;
      attempted=true;loading=true;error='';paint();
      try{
        const result=await request('/api/insights/charging-review?date='+encodeURIComponent(target+'-01'),undefined,50000,{signal:controller.signal,active});
        if(!valid(token)||target!==month)return;if(result.context!==owner)throw Error('账号或车辆已切换，请重新读取。');
        data=result;loadedMonth=target;
        if(!data.records.some(e=>e.id===expanded))expanded='';
      }catch(failure){if(valid(token))error=failure.message;}
      finally{if(valid(token)){loading=false;paint();}}
    }
    function suspend(){if(loading){controller?.abort();serial++;loading=false;attempted=false;}}
    function mount(container){
      if(!container||!active())return;
      const identity=context(),nextRevision=JSON.stringify([getState()?.charge_records_revision,getState()?.trip_records_revision,root.recallPersonalRevision]);
      const changed=owner!==identity,updated=revision!==nextRevision;
      node=container;
      if(changed){suspend();owner=identity;data=null;loadedMonth=expanded=error='';pending=false;attempted=false;}
      revision=nextRevision;paint();
      if(owner&&(!data&&!attempted&&!loading||updated&&!loading))load();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;
      if(event.type==='change'&&event.target.id==='charging-review-month'){
        if(month!==event.target.value){month=event.target.value;suspend();data=null;expanded='';pending=false;paint();load();}return true;
      }
      if(event.type!=='click')return false;
      const target=event.target.closest('[data-review]');if(!target||target.disabled)return false;
      const action=target.dataset.review;
      if(action==='load')load();
      if(action==='today'){month=dateAt(Date.now()).slice(0,7);pending=false;expanded='';data=null;load();}
      if(action==='pending'){pending=!pending;expanded='';paint();}
      if(action==='expand'){expanded=expanded===target.dataset.reviewExpand?'':target.dataset.reviewExpand;paint();}
      if(action==='curve'||action==='ledger'){
        const row=data?.records.find(e=>e.id===target.dataset.id);if(row)(action==='curve'?openRecord:openLedger)(row);
      }
      return true;
    }
    root.addEventListener('resize',()=>{if(active()&&node?.isConnected)guides();});
    return {mount,handle,suspend};
  }
  root.ChargingReviewPage={create};
})(window);
