(function(root){
  'use strict';
  const dateOf=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const money=value=>Number.isFinite(value)?(value/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
  const num=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:3}).format(value):'—';
  const sources={home:'家充',public:'外充',unknown:'未分类'};
  const formFields=['event_id','date','source','amount','metered_kwh','unit_price','service_fee','note'];
  const blank=date=>({id:'',event_id:'',date,source:'unknown',amount:'',metered_kwh:'',unit_price:'',service_fee:'',note:''});
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',month=dateOf(Date.now()).slice(0,7),data=null,attempted=false,loading=false,busy=false;
    let serial=0,writeSerial=0,error='',status='',draft=blank(dateOf(Date.now())),page=0,trashPage=0;
    const context=()=>getState()?.insights_context||'';
    const valid=(token,current,identity)=>token===current&&identity===owner&&identity===context();
    const defaultDate=()=>dateOf(Date.now()).startsWith(month)?dateOf(Date.now()):month+'-01';
    const button=(label,action,disabled=false,extra='')=>`<button class="button secondary" data-ledger="${action}" ${disabled||busy?'disabled':''} ${extra}>${label}</button>`;
    function field(label,name,type='number',step='.01',extra=''){
      return `<label>${label}<input id="ledger-${name}" name="${name}" type="${type}" ${type==='number'?`min="0" step="${step}"`:''} value="${esc(draft[name])}" ${extra}></label>`;
    }
    function paint(){
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const t=data?.totals;
      const choices=(data?.events||[]).slice();
      if(draft.event_id&&!choices.some(row=>row.id===draft.event_id)){
        const entry=data?.entries.find(row=>row.id===draft.id),linked=entry?.event;
        if(linked)choices.unshift(linked);
        else if(entry?.source_event_removed)choices.unshift({id:entry.source_event_id,removed:true,recorded:true});
      }
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">充电账本</span><h2>花了多少，有账可查</h2><p>真实账单与估算各自列清，留空就保持未知。</p></div><span class="insight-source">手工记录 · 本机保存</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>账本月份<input id="ledger-month" type="month" value="${esc(month)}"></label>${button('读取账本','load',!owner||!month,'id="ledger-load"')}${button('撤销上一步','undo',!data?.can_undo)}</div>${loading?'<p role="status">正在读取账本…</p>':''}${status?`<p role="status" class="insight-note">${esc(status)}</p>`:''}${error?`<div class="notice error" role="alert">${esc(error)}</div>`:''}${!owner?'<p>连接车辆账号并取得当前车辆绑定后，可管理账本。</p>':''}${data?`<p id="ledger-range" class="insight-note">账本月份 ${data.window.start_date.slice(0,7)} · 按账单日期归期。本月有 ${data.events.length} 条结束充电记录，其中 ${data.events.filter(row=>row.recorded).length} 条已关联账单。未关联不代表免费充电。</p>`:''}</section>
        ${data?`<div class="insight-metrics report-totals"><div id="ledger-actual-total"><span>已填实际金额</span><strong>${money(t.actual_cents)} <small>元</small></strong><small>${t.actual_count} 笔账单</small></div><div><span>其余未填账单的估算</span><strong>${money(t.unbilled_estimated_cents)} <small>元</small></strong><small>${t.estimated_count} 笔估算；未并入实际金额</small></div><div><span>费用仍未知</span><strong>${t.unpriced_count} <small>笔</small></strong><small>缺少实际金额或估算依据</small></div><div><span>已录桩端计量电量</span><strong>${num(t.metered_kwh)} <small>kWh</small></strong><small>${t.metered_count} 笔有计量值</small></div></div>
        <section class="card insight-panel"><div class="insight-heading"><h3>${draft.id?'编辑账单':'新增账单'}</h3>${button('新增手工账单','new')}</div><form id="ledger-form" class="ledger-form" novalidate><label class="ledger-wide">关联充电记录<select id="ledger-event_id" name="event_id" aria-label="关联充电记录" ${draft.id?'disabled':''}><option value="">手工补录，不关联记录</option>${choices.map(row=>`<option value="${esc(row.id)}" ${draft.event_id===row.id?'selected':''} ${row.recorded&&draft.event_id!==row.id?'disabled':''}>${row.removed?'已移入回收区的关联记录':`${esc(time(row.end_time))} · ${num(row.start_soc)}% → ${num(row.end_soc)}%${row.partial?' · 片段':''}${row.recorded?' · 已记账':''}`}</option>`).join('')}</select></label>${field('账单日期','date','date','', 'required')}<label>充电来源<select id="ledger-source" name="source" aria-label="充电来源">${Object.entries(sources).map(([key,label])=>`<option value="${key}" ${draft.source===key?'selected':''}>${label}</option>`).join('')}</select></label>${field('实际账单金额（元）','amount')}${field('桩端计量电量（kWh）','metered_kwh','number','.001')}${field('参考电价（元/kWh）','unit_price','number','.0001')}${field('估算附加费用（元）','service_fee')}<label class="ledger-wide">账单备注<textarea id="ledger-note" name="note" aria-label="账单备注" maxlength="1000" rows="3">${esc(draft.note)}</textarea></label></form><p class="insight-note">实际金额填写已含各项费用的最终账单总额。电价与附加费用只用于估算；优先用桩端计量电量，缺失时才用关联事件的 SOC 电量估算。0 是明确零值，留空是未知。</p><div class="insight-actions">${button(busy?'正在保存…':'保存账单','save',!owner||loading)}${draft.id?button('取消编辑','new'):''}</div></section>
        <section class="card insight-panel"><h3>本月账单</h3><div id="ledger-entries"></div></section>
        <section class="card insight-panel" id="ledger-sources"><h3>充电来源占比</h3><p class="insight-note">按本月已录账单笔数计算；未分类也保留。费用仍区分实际与估算。</p><div class="report-comparison">${Object.entries(data.sources).map(([key,value])=>`<article><strong>${sources[key]} · ${value.count} 笔</strong><span>笔数占比 ${t.count?num(value.count/t.count*100)+'%':'—'}</span><span>实际 ${money(value.actual_cents)} 元</span><span>其余估算 ${money(value.unbilled_estimated_cents)} 元</span></article>`).join('')}</div></section>
        <section class="card insight-panel"><h3>近六个月费用记录</h3><div class="ledger-trend">${data.trend.map(row=>`<article><strong>${row.month}</strong><span>实际 ${money(row.actual_cents)} 元</span><span>其余估算 ${money(row.unbilled_estimated_cents)} 元</span><small>${row.count} 笔记录 · ${row.unpriced_count} 笔费用未知</small></article>`).join('')}</div></section>
        <section class="card insight-panel"><h3>本期每公里费用参考</h3><div class="parking-row-values"><span>仅已填实际费用<strong>${num(data.cost_per_km.actual_yuan)} 元/km</strong></span><span>实际加其余估算费用<strong>${num(data.cost_per_km.including_estimates_yuan)} 元/km</strong></span></div><p class="insight-note">本期已录充电费用 ÷ 本期 ${data.cost_per_km.distance_samples} 条有效记录的 ${num(data.cost_per_km.distance_km)} km，含 ${data.cost_per_km.partial_distance_samples} 条片段，均为已观测里程。充入电量可能跨期使用，且费用和里程都可能缺记录。这是账期参考，不是每趟行程实际用电成本。</p></section>
        <div id="ledger-trash"></div>`:''}`;
      paintRows();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function paintRows(){
      if(!data||!node?.querySelector('#ledger-entries'))return;
      const pages=Math.max(1,Math.ceil(data.entries.length/10));page=Math.min(page,pages-1);
      node.querySelector('#ledger-entries').innerHTML=data.entries.length?`<div class="report-event-list">${data.entries.slice(page*10,page*10+10).map(row=>`<article data-ledger-entry="${esc(row.id)}"><div class="insight-heading"><h4>${row.date} · ${sources[row.source]}</h4><span class="insight-badge">${row.event?'关联充电记录':row.source_event_removed?'关联记录已移入回收区':'手工补录'}</span></div><div class="parking-row-values"><span>实际金额<strong>${money(row.actual_cents)} 元</strong></span><span>参考估算<strong>${money(row.estimated_cents)} 元</strong></span><span>桩端计量电量<strong>${num(row.metered_kwh)} kWh</strong></span><span>估算依据<strong>${{metered_price:'计量电量 × 电价 + 附加费用',soc_price:'SOC 电量估算 × 电价 + 附加费用'}[row.estimate_basis]||'依据不足，不计算'}</strong></span></div>${row.event?`<p class="insight-note">充电结束 ${esc(time(row.event.end_time))} · 事件电量估算 ${num(row.event.estimated_kwh)} kWh · 事件记录容量 ${num(row.event.battery_capacity_kwh)} kWh</p>`:row.source_event_removed?'<p class="insight-note">关联充电记录已移入回收区；人工填写内容保留，SOC 自动估算已停用。</p>':''}${row.note?`<p class="ledger-note">${esc(row.note)}</p>`:''}<div class="insight-actions">${button('编辑账单','edit',false,`data-id="${esc(row.id)}"`)}${button('删除账单','delete',false,`data-id="${esc(row.id)}"`)}</div></article>`).join('')}</div><div class="insight-pagination">${button('上一页账单','previous',page===0)}<span>${page+1} / ${pages}</span>${button('下一页账单','next',page+1===pages)}</div>`:'<p class="insight-empty">本月还没有账单</p>';
      const trashPages=Math.max(1,Math.ceil(data.trash.length/10));trashPage=Math.min(trashPage,trashPages-1);
      node.querySelector('#ledger-trash').innerHTML=data.trash.length?`<section class="card insight-panel"><h3>已删除账单 · 可恢复</h3><div class="ledger-trash-list">${data.trash.slice(trashPage*10,trashPage*10+10).map(row=>`<div><span>${row.date} · ${sources[row.source]} · 实际 ${money(row.actual_cents)} 元</span>${button('恢复账单','restore',false,`data-id="${esc(row.id)}"`)}</div>`).join('')}</div><div class="insight-pagination">${button('上一页已删除','trash-previous',trashPage===0)}<span>${trashPage+1} / ${trashPages}</span>${button('下一页已删除','trash-next',trashPage+1===trashPages)}</div></section>`:'';
    }
    async function load(){
      if(!owner||!month)return;
      const identity=owner,token=++serial;loading=true;attempted=true;error='';paint();
      try{
        const result=await request('/api/insights/ledger?date='+encodeURIComponent(month+'-01'));
        if(!valid(token,serial,identity))return false;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新加载。');
        data=result;page=0;trashPage=0;return true;
      }catch(failure){if(valid(token,serial,identity))error=failure.message;return false;}
      finally{if(valid(token,serial,identity)){loading=false;paint();}}
    }
    async function mutate(action,id){
      if(!data||busy||loading)return;
      if(action==='save'){
        const form=node.querySelector('#ledger-form');
        if(!form.checkValidity()){form.reportValidity();return;}
      }
      const identity=owner,token=++writeSerial;
      const payload={...(action==='save'?draft:{}),action,id:action==='save'?draft.id:id,revision:data.revision,context:owner};
      busy=true;error='';status='';paint();
      try{
        const result=await request('/api/insights/ledger',payload);
        if(!valid(token,writeSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新加载。');
        data.revision=result.revision;data.can_undo=result.can_undo;
        status={save:'账单已保存。',delete:'账单已删除，可在下方恢复或撤销。',restore:'账单已恢复。',undo:'上一步已撤销。'}[action];
        if(action==='save'){month=result.saved_date.slice(0,7);draft=blank(defaultDate());}
        else if(action==='delete'&&draft.id===id)draft=blank(defaultDate());
        const refreshed=await load();
        if(!refreshed&&valid(token,writeSerial,identity))status+=' 列表尚未刷新，请重新读取账本核对。';
      }catch(failure){if(valid(token,writeSerial,identity))error=failure.message+' 填写内容保留；请重新读取账本核对后再操作。';}
      finally{if(valid(token,writeSerial,identity)){busy=false;paint();}}
    }
    function edit(id){
      const row=data.entries.find(row=>row.id===id);if(!row)return;
      draft={id:row.id,event_id:row.source_event_id||'',date:row.date,source:row.source,
        amount:row.actual_cents===null?'':(row.actual_cents/100).toFixed(2),metered_kwh:row.metered_kwh??'',
        unit_price:row.unit_price??'',service_fee:row.service_fee_cents===null?'':(row.service_fee_cents/100).toFixed(2),note:row.note};
      error='';paint();node.querySelector('#ledger-form').scrollIntoView({block:'start'});
    }
    let tripRevision,chargeRevision;
    function mount(container){
      const changed=owner!==context(),recordsChanged=!busy&&(tripRevision!==getState()?.trip_records_revision||chargeRevision!==getState()?.charge_records_revision),remount=node!==container;node=container;
      if(changed||recordsChanged){tripRevision=getState()?.trip_records_revision;chargeRevision=getState()?.charge_records_revision;}
      if(changed){owner=context();data=null;attempted=false;loading=false;busy=false;serial++;writeSerial++;error='';status='';draft=blank(defaultDate());}
      else if(recordsChanged){data=null;attempted=loading=false;serial++;}
      if(changed||recordsChanged||remount)paint();if(owner&&!attempted&&!loading)load();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;
      const el=event.target;
      if(event.type==='input'&&el.id==='ledger-month'){month=el.value;node.querySelector('#ledger-load').disabled=!owner||!month||busy;return true;}
      if((event.type==='input'||event.type==='change')&&formFields.includes(el.name)){
        draft[el.name]=el.value;
        if(el.name==='event_id'){
          const row=data?.events.find(row=>row.id===el.value);
          if(row){draft.date=dateOf(row.end_time);node.querySelector('#ledger-date').value=draft.date;}
        }
        return true;
      }
      if(event.type!=='click')return false;
      const target=el.closest('[data-ledger]');if(!target||target.disabled)return false;
      switch(target.dataset.ledger){
        case 'load':load();break;
        case 'new':draft=blank(defaultDate());error='';paint();break;
        case 'save':mutate('save');break;
        case 'delete':case 'restore':case 'undo':mutate(target.dataset.ledger,target.dataset.id);break;
        case 'edit':edit(target.dataset.id);break;
        case 'previous':page--;paintRows();break;
        case 'next':page++;paintRows();break;
        case 'trash-previous':trashPage--;paintRows();break;
        case 'trash-next':trashPage++;paintRows();break;
      }
      return true;
    }
    return {mount,handle};
  }
  root.ChargeLedgerPage={create};
})(window);
