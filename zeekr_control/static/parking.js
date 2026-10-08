(function(root) {
  'use strict';
  const categories={same_day:'日内停车',overnight:'跨夜停车',multi_day:'停放多天'};
  const number=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:3}).format(value):'未知';
  const dateAt=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  function durationLabel(seconds){
    if(!Number.isFinite(seconds)||seconds<0)return '时长未知';
    const minutes=Math.floor(seconds/60),days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60),rest=minutes%60;
    return [days?`${days}天`:'',hours?`${hours}小时`:'',rest?`${rest}分`:''].join('')||'不足1分';
  }
  function calendarModel(events,start,end,month){
    const lower=Date.parse(`${start}T00:00:00Z`),upper=Date.parse(`${end}T00:00:00Z`),months=[];
    if(!Number.isFinite(lower)||!Number.isFinite(upper)||upper<lower||upper-lower>30*86400000)return {months,month:null,offset:0,days:[]};
    for(let day=lower;day<=upper;day+=86400000){const key=new Date(day).toISOString().slice(0,7);if(!months.includes(key))months.push(key);}
    if(!months.includes(month))month=months[0];
    const first=new Date(`${month}-01T00:00:00Z`),count=new Date(Date.UTC(first.getUTCFullYear(),first.getUTCMonth()+1,0)).getUTCDate();
    const valid=events.filter(e=>Number.isFinite(e.start_time)&&Number.isFinite(e.end_time)&&e.end_time>=e.start_time)
      .map(event=>({event,start:dateAt(event.start_time),end:dateAt(event.end_time)}));
    const days=Array.from({length:count},(_,i)=>{
      const date=`${month}-${String(i+1).padStart(2,'0')}`,inRange=date>=start&&date<=end;
      const rows=inRange?valid.filter(e=>e.start<=date&&e.end>=date).map(e=>({event:e.event,full:e.end===date})):[];
      return {date,inRange,rows};
    });
    return {months,month,offset:(first.getUTCDay()+6)%7,days};
  }
  function create({getState,request,escape:esc,active,time}) {
    let node=null,owner='',start=dateAt(Date.now()-6*86400000),end=dateAt(Date.now());
    let data=null,error='',loading=false,serial=0,category='all',quality='all',order='latest',page=0;
    let selected=null,comparison=null,compareError='',comparing=false,compareSerial=0;
    let calendarMonth='',expandedDays=new Set();
    function identity(){return getState()?.insights_context || '';}
    function valid(token,current,context){return token===current && owner===context && context===identity();}
    function button(label,action,disabled=false,extra=''){return `<button class="button secondary" data-parking="${action}" ${disabled?'disabled':''} ${extra}>${label}</button>`;}
    function rows(){
      if(data?.events){
        return data.events.filter(row=>(category==='all'||category===row.category) && (quality==='all'||row.status==='comparable'))
          .sort((a,b)=>order==='drop'?(Number(b.status==='comparable')-Number(a.status==='comparable') || (b.soc_drop??-1)-(a.soc_drop??-1) || b.start_time-a.start_time):b.start_time-a.start_time);
      }
      const result=(data?.sessions || []).filter(row=>(category==='all' || category===row.category) && (quality==='all' || row.eligible));
      return result.sort((a,b)=>order==='drop'?Number(b.eligible)-Number(a.eligible) || (b.eligible?(b.soc_drop??0)-(a.soc_drop??0):b.start_time-a.start_time):b.start_time-a.start_time);
    }
    function paintCalendar(){
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const list=rows(),model=data?calendarModel(list,data.start_date,data.end_date,calendarMonth):null;
      if(model)calendarMonth=model.month;
      node.innerHTML=`<section class="parking-calendar-heading"><div><h2>停车观测</h2><p>停在哪里 · 停了多久 · 消耗多少电量</p></div><span class="insight-source">SOC 观测 · 非电表计量</span></section>
        <section class="card insight-panel parking-calendar-controls"><div class="insight-toolbar"><label>开始日期<input id="parking-start" type="date" value="${esc(start)}"></label><label>结束日期<input id="parking-end" type="date" value="${esc(end)}"></label>${button(loading?'正在分析…':'分析停车观测','load',loading||!owner||!start||!end,'id="parking-load"')}</div>
        ${!data?'<p class="insight-note">选择日期后点击分析，最多查看 31 天。</p>':''}${!owner?'<p>连接车辆账号并取得当前车辆绑定后，可分析停车观测。</p>':''}${loading?'<p role="status">正在分析本机归档…</p>':''}${error?`<div class="notice error" role="alert">${esc(error)}${data?' · 保留上次结果与原日期范围。':''}</div>`:''}</section>
        ${data?`<section class="card insight-panel parking-calendar-panel"><div class="parking-calendar-month"><h3>${esc(calendarMonth?.replace('-',' 年 '))} 月</h3><div class="insight-actions">${model.months.length>1?`${button('上一月','month-previous',model.months.indexOf(calendarMonth)===0)}${button('下一月','month-next',model.months.indexOf(calendarMonth)===model.months.length-1)}`:''}<details class="parking-calendar-filters"><summary>筛选</summary><div class="insight-toolbar"><label>停车时段<select id="parking-category" aria-label="停车时段"><option value="all">全部时段</option>${Object.entries(categories).map(([key,label])=>`<option value="${key}" ${category===key?'selected':''}>${label}</option>`).join('')}</select></label><label>耗电可信度<select id="parking-quality" aria-label="耗电可信度"><option value="all">全部停车事件</option><option value="eligible" ${quality==='eligible'?'selected':''}>只看可计算</option></select></label></div></details></div></div>
          <div class="parking-calendar-week" aria-hidden="true">${['一','二','三','四','五','六','日'].map(day=>`<span>周${day}</span>`).join('')}</div><div class="parking-calendar-grid" aria-label="停车日历">${'<span class="parking-calendar-blank" aria-hidden="true"></span>'.repeat(model.offset)}${model.days.map(day=>{
            const visible=expandedDays.has(day.date)?day.rows:day.rows.slice(0,3);
            return `<article class="parking-calendar-day ${day.inRange?'':'outside'}" data-parking-date="${day.date}" aria-label="${day.date}" ${day.date===dateAt(Date.now())?'aria-current="date"':''}><div class="parking-calendar-date"><strong>${Number(day.date.slice(-2))}</strong><small>${day.rows.length?`${day.rows.length} 条`:''}</small></div>${visible.map(entry=>calendarEntry(entry,day.date)).join('')}${day.rows.length>visible.length?button(`还有 ${day.rows.length-visible.length} 次 · 展开`,'expand-day',false,`data-date="${day.date}"`):''}${!day.rows.length?`<p class="parking-calendar-empty">${day.inRange?'没有符合筛选的记录':'范围外'}</p>`:''}</article>`;
          }).join('')}${'<span class="parking-calendar-blank" aria-hidden="true"></span>'.repeat((7-(model.offset+model.days.length)%7)%7)}</div>${!list.length?'<p class="insight-empty">没有符合筛选的停车事件</p>':''}
          <details class="parking-calendar-notes"><summary>数据说明 · ${data.parking_count??list.filter(r=>r.parking_status==='parked'||r.status==='comparable').length} 条停车记录 · ${data.uncertain_count??0} 条耗电未知</summary><p id="parking-range" class="insight-note">结果范围：${esc(data.start_date)} 至 ${esc(data.end_date)} · 计算规则 v${data.calculation_version}</p><p>跨日停车在涉及日期标记，完整时长与耗电只归结束日，不拆分或重复累计。结束日在查询范围外时，日格仅显示跨日标记。</p><p>没有记录不代表没有停车。超过 10 分钟的观测缺口、充电、位置变化或不完整边界等会阻止耗电计算；未知不算零。最后一条开放记录只展示已观测时长，不代表车辆仍在停车。</p><p>电量估算 = 档案电池容量 × SOC 下降百分点 ÷ 100。未见 SOC 下降不证明实际耗电为零。地点匹配已保存区域或本地地址；位置不足显示未知。</p>${data.orphan_count?`<details><summary>无行程边界的旧观测（${data.orphan_count}）</summary><p>以下仅供核对，不计入停车统计。</p>${(data.orphan_sessions||[]).map(row=>`<p>${esc(time(row.start_time))} 至 ${esc(time(row.end_time))} · ${(row.reason_labels||[]).map(esc).join('；')}</p>`).join('')}</details>`:''}</details></section>`:''}<div id="parking-detail"></div>`;
      paintDetail();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function calendarEntry({event:row,full},date){
      const duration=durationLabel(row.duration_seconds),parked=row.parking_status==='parked'||row.status==='comparable';
      const comparable=row.status==='comparable'&&Number.isFinite(row.soc_drop);
      const energy=comparable?(row.soc_drop===0?'未见 SOC 下降':`下降 ${number(row.soc_drop)} 个百分点`):'耗电未知';
      const endDate=dateAt(row.end_time),clock=value=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));
      const span=`${dateAt(row.start_time)===date?'':`${Number(dateAt(row.start_time).slice(5,7))}月${Number(dateAt(row.start_time).slice(-2))}日 `}${clock(row.start_time)} — ${clock(row.end_time)}`;
      const continuation=`${Number(endDate.slice(5,7))}月${Number(endDate.slice(-2))}日查看完整记录`;
      return `<button class="parking-calendar-entry ${!parked||full&&!comparable?'uncertain':''} ${full?'':'continued'}" data-parking="select" data-session="${esc(row.id)}" data-parking-entry="${esc(row.id)}" ${full?`data-parking-session="${esc(row.id)}"`:''} aria-label="查看停车详情：${esc(row.place_label||'位置未知')}，${full?esc(duration+'，'+energy):'跨日停车'}"><strong class="parking-calendar-place">${esc(row.place_label||'位置未知')}</strong>${!parked?'<span class="parking-calendar-status">停车待确认</span>':''}<span class="parking-calendar-values"><span>${full?`${row.open?'已观测 ':!parked?'候选 ':''}${duration}`:'跨日停放'}</span><strong>${full?energy:esc(continuation)}</strong></span>${full?`<span class="parking-calendar-energy">${comparable&&Number.isFinite(row.estimated_kwh)?`约 ${number(row.estimated_kwh)} kWh`:comparable?'容量未配置':''}</span>`:''}<span class="parking-calendar-time">${full?esc(span):`${dateAt(row.start_time)===date?clock(row.start_time)+' 开始':'承接前日'}`}${full&&row.open?' · 后续行程未记录':''}</span></button>`;
    }
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected || !active())return;
      if(!data||data.events){paintCalendar();return;}
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const list=rows();
      const pages=Math.max(1,Math.ceil(list.length/12));page=Math.min(page,pages-1);
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">停车耗电观察</span><h2>停下来以后，电量怎样变</h2><p>沿着有效观测看变化，保留每一处不确定。</p></div><span class="insight-source">SOC 观测 · 非电表计量</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>开始日期<input id="parking-start" type="date" value="${esc(start)}"></label><label>结束日期<input id="parking-end" type="date" value="${esc(end)}"></label>${button('分析停车观测','load',loading || !owner || !start || !end,'id="parking-load"')}</div><p class="insight-note">选择时间范围后点击“分析停车观测”。最多查看 31 天。仅比较有开始、结束边界且连续有效的停车观测；首末时间为已观测到的停车端点。</p>
        ${loading?'<p role="status">正在分析本机归档…</p>':''}${!owner?'<p>连接车辆账号并取得当前车辆绑定后，可分析停车观测。</p>':''}${error?`<div class="notice error" role="alert">${esc(error)}${data?' · 保留上次结果与原日期范围。':''}</div>`:''}
        ${data?`<p id="parking-range" class="insight-note">结果范围：${esc(data.start_date)} 至 ${esc(data.end_date)} · ${data.quality.read_count} 条范围内读取，另有 ${data.quality.boundary_reads} 条边界观测；${data.quality.repeat_reads} 次重复缓存，${data.quality.revisions} 次同时间修订。</p><div class="insight-metrics parking-counts"><div><span>可比较区间</span><strong>${data.eligible_count}</strong></div><div><span>证据不完整片段</span><strong>${data.fragment_count}</strong></div><div><span>无效或不确定观测</span><strong>${data.quality.excluded_reads}</strong></div></div>`:''}</section>
        ${data?`<section class="card insight-panel"><div class="insight-toolbar"><label>停车时段<select id="parking-category" aria-label="停车时段"><option value="all">全部时段</option>${Object.entries(categories).map(([key,label])=>`<option value="${key}" ${category===key?'selected':''}>${label}</option>`).join('')}</select></label><label>观测完整性<select id="parking-quality" aria-label="观测完整性"><option value="all">全部区间与片段</option><option value="eligible" ${quality==='eligible'?'selected':''}>只看可比较区间</option></select></label><label>排列方式<select id="parking-order" aria-label="排列方式"><option value="latest">最近停车优先</option><option value="drop" ${order==='drop'?'selected':''}>较大 SOC 下降优先</option></select></label></div><p class="insight-note">匹配 ${list.length} 个区间。按 SOC 下降排列时，片段单列在可比较区间之后；时长不同，不能直接归因为车辆异常。</p>
          <div class="parking-list">${list.slice(page*12,page*12+12).map(row=>`<article data-parking-session="${esc(row.id)}"><div class="insight-heading"><h3>${categories[row.category]}</h3><span class="insight-badge ${row.eligible?'':'insight-warning'}">${row.eligible?'可比较':'观测片段'}</span></div><p>${esc(time(row.start_time))} → ${esc(time(row.end_time))}</p><div class="parking-row-values"><span>观测时长<strong>${number(row.duration_seconds/3600)} 小时</strong></span><span>SOC 端点<strong>${number(row.start_soc)}% → ${number(row.end_soc)}%</strong></span><span>SOC 下降<strong>${number(row.soc_drop)} 个百分点</strong></span><span>电量估算<strong>${row.estimated_kwh===null?'不计算':number(row.estimated_kwh)+' kWh'}</strong></span></div>${!row.eligible?`<p class="insight-note">${row.reason_labels.map(esc).join('；')}</p>`:''}${button('查看区间详情','select',false,`data-session="${esc(row.id)}"`)}</article>`).join('') || '<div class="insight-empty"><h3>没有符合筛选的停车区间</h3><p>可换日期或放宽筛选。没有有效停车证据，不等于没有停车。</p></div>'}</div><div class="insight-pagination">${button('上一页区间','previous',page===0)}<span>第 ${page+1} / ${pages} 页</span>${button('下一页区间','next',page+1===pages)}</div></section>`:''}
        <div id="parking-detail"></div><div id="parking-compare"></div>
        <p class="insight-note">估算 = 当前档案电池容量 × SOC 下降百分点 ÷ 100。容量${data?.capacity_kwh?'：'+number(data.capacity_kwh)+' kWh':'未配置时不换算电量'}。SOC 显示精度、温度变化和电池估算修正都会影响结果；0 个百分点不证明实际耗电为零。采集/车辆时间间隔超过 10 分钟会切开区间。</p>`;
      paintDetail();paintComparison();
      if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function paintDetail(){
  return root.RefreshView?root.RefreshView.preserve(node,()=>paintDetailContent()):paintDetailContent();
}
function paintDetailContent(){
      const el=node?.querySelector('#parking-detail');if(!el)return;
      if(data?.events){
        const row=data.events.find(item=>item.id===selected);
        el.innerHTML=row?`<section class="card insight-panel"><div class="insight-heading"><h3>${esc(row.place_label||'位置未知')} · 停车详情</h3>${button('收起停车详情','close-detail')}</div><p>${esc(time(row.start_time))} → ${esc(time(row.end_time))}</p><div class="parking-row-values"><span>${row.open?'已观测停车时长':row.parking_status==='parked'||row.status==='comparable'?'停车时长':'候选时长'}<strong>${durationLabel(row.duration_seconds)}</strong></span><span>耗电<strong>${row.status==='comparable'&&Number.isFinite(row.soc_drop)?`${number(row.soc_drop)} 个百分点`:'耗电未知'}</strong><small>${row.status==='comparable'&&Number.isFinite(row.estimated_kwh)?`约 ${number(row.estimated_kwh)} kWh`:'电量暂不换算'}</small></span><span>来源行程<strong>${row.start_trip_id?esc(row.start_trip_id):'查询起点'} → ${row.open?'后续行程未记录':esc(row.end_trip_id)}</strong></span><span>范围内观测<strong>${number(row.sample_count)} 条</strong></span><span>超过 10 分钟的缺口<strong>${number(row.gap_count)} 处</strong></span><span>SOC 端点<strong>${number(row.start_soc)}% → ${number(row.end_soc)}%</strong></span><span>P 档辅助证据<strong>${number(row.p_gear_samples??0)} 条有效观测</strong><small>用户指定映射：0=P、1=R、2=N、3=D</small></span></div><p class="insight-note">${row.status==='comparable'?'起止边界和中间观测可比较；SOC 变化不是电表计量。':'不计算耗电：'+(row.reason_labels||[]).map(esc).join('；')} 历史原始数据未改写。</p></section>`:'';
        return;
      }
      const row=data?.sessions.find(row=>row.id===selected);
      if(!row){el.innerHTML='';return;}
      el.innerHTML=`<section class="card insight-panel"><h3>区间详情</h3><p>${esc(time(row.start_time))} → ${esc(time(row.end_time))}</p><div class="parking-row-values"><span>有效停车样本<strong>${row.sample_count} 条</strong></span><span>最大有效观测间隔<strong>${number(row.max_gap_seconds)} 秒</strong></span><span>里程端点<strong>${number(row.start_km)} → ${number(row.end_km)} km</strong></span><span>座舱温度端点<strong>${number(row.start_inside_temp)} → ${number(row.end_inside_temp)} °C</strong><small>独立更新时间 ${esc(time(row.start_inside_time))} → ${esc(time(row.end_inside_time))}</small></span><span>采集端点<strong>${esc(time(row.start.observed_at))}<br>${esc(time(row.end.observed_at))}</strong></span><span>按 24 小时折算 SOC 下降<strong>${row.soc_drop_per_24h===null?'不计算':number(row.soc_drop_per_24h)+' 个百分点'}</strong></span></div><p class="insight-note">${row.eligible?'已观测到前后非停车状态，区间内没有充电或已知数据缺口。':'不完整原因：'+row.reason_labels.map(esc).join('；')} 按日折算仅适用于至少 1 小时的可比较区间，不能预测未来耗电。</p>${button('比较停车端点参数','compare',comparing || row.start.key===row.end.key)}</section>`;
    }
    function paintComparison(){
  return root.RefreshView?root.RefreshView.preserve(node,()=>paintComparisonContent()):paintComparisonContent();
}
function paintComparisonContent(){
      const el=node?.querySelector('#parking-compare');if(!el)return;
      el.innerHTML=compareError?`<p class="notice error" role="alert">${esc(compareError)}</p>`:comparing?'<p role="status">正在比较停车端点…</p>':comparison?`<section class="card insight-panel"><h3>停车端点参数变化</h3><p class="insight-note">${esc(time(comparison.before.state_time))} → ${esc(time(comparison.after.state_time))} · ${comparison.changes.length} 项变化</p><div class="insight-diff">${comparison.changes.map(row=>`<article data-parking-change="${esc(row.path)}"><strong>${esc(row.name)}</strong><div><span>停车起点</span><b>${esc(row.before.value)}</b><small>原值 ${esc(row.before.raw)}</small></div><div><span>停车终点</span><b>${esc(row.after.value)}</b><small>原值 ${esc(row.after.raw)}</small></div></article>`).join('') || '<p>安全目录参数值没有变化。</p>'}</div></section>`:'';
    }
    async function load(){
      if(loading || !owner || !start || !end)return;
      const context=owner,token=++serial;
      loading=true;error='';paint();
      try{
        const result=await request(`/api/insights/parking?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`, undefined, 180000);
        if(!valid(token,serial,context))return;
        if(result.context!==context)throw Error('账号或车辆已切换，请重新读取。');
        data=result;page=0;calendarMonth='';expandedDays.clear();selected=null;comparison=null;compareError='';compareSerial++;comparing=false;
      }catch(failure){if(valid(token,serial,context))error=failure.message;}
      finally{if(valid(token,serial,context)){loading=false;paint();}}
    }
    async function compare(){
      if(data?.events)return;
      const row=data?.sessions.find(row=>row.id===selected);if(!row)return;
      const context=owner,token=++compareSerial;
      comparing=true;comparison=null;compareError='';paintDetail();paintComparison();
      try{
        const result=await request(`/api/insights/compare?before=${encodeURIComponent(row.start.key)}&after=${encodeURIComponent(row.end.key)}`);
        if(!valid(token,compareSerial,context))return;
        if(result.context!==context)throw Error('账号或车辆已切换，请重新比较。');
        comparison=result;
      }catch(failure){if(valid(token,compareSerial,context))compareError=failure.message;}
      finally{if(valid(token,compareSerial,context)){comparing=false;if(active()){paintDetail();paintComparison();}}}
    }
    function mount(container){
      const changed=owner!==identity(),remount=node!==container;
      node=container;
      if(changed){owner=identity();data=null;loading=false;error='';calendarMonth='';expandedDays.clear();selected=null;comparison=null;compareError='';comparing=false;serial++;compareSerial++;}
      if(changed || remount)paint();
    }
    function handle(event){
      if(!active() || !node?.contains(event.target))return false;
      const el=event.target;
      if(event.type==='input' && ['parking-start','parking-end'].includes(el.id)){
        if(el.id==='parking-start')start=el.value;else end=el.value;
        data=null;loading=false;error='';calendarMonth='';expandedDays.clear();selected=null;comparison=null;compareError='';comparing=false;page=0;serial++;compareSerial++;paint();return true;
      }
      if(event.type==='change'){
        if(el.id==='parking-category')category=el.value;
        else if(el.id==='parking-quality')quality=el.value;
        else if(el.id==='parking-order')order=el.value;
        else return false;
        page=0;expandedDays.clear();paint();return true;
      }
      if(event.type!=='click')return false;
      const target=el.closest('[data-parking]');if(!target || target.disabled)return false;
      if(target.dataset.parking==='load')load();
      if(target.dataset.parking==='compare')compare();
      if(target.dataset.parking==='previous'){page--;paint();}
      if(target.dataset.parking==='next'){page++;paint();}
      if(['month-previous','month-next'].includes(target.dataset.parking)&&data?.events){
        const model=calendarModel(rows(),data.start_date,data.end_date,calendarMonth);
        const index=model.months.indexOf(calendarMonth)+(target.dataset.parking==='month-next'?1:-1);
        if(model.months[index]){calendarMonth=model.months[index];paint();}
      }
      if(target.dataset.parking==='expand-day'){expandedDays.add(target.dataset.date);paint();}
      if(target.dataset.parking==='close-detail'){selected=null;paintDetail();}
      if(target.dataset.parking==='select'){
        selected=target.dataset.session;comparison=null;compareError='';compareSerial++;comparing=false;
        paintDetail();paintComparison();node.querySelector('#parking-detail').scrollIntoView({block:'start',behavior:'auto'});
      }
      return true;
    }
    function openDate(date){
      start=end=date;data=null;loading=false;error='';selected=null;comparison=null;
      category=quality='all';page=0;calendarMonth='';expandedDays.clear();serial++;compareSerial++;compareError='';comparing=false;
    }
    return {mount,handle,openDate};
  }
  root.ParkingPage={create,calendarModel,durationLabel};
})(window);
