(function(root){
  'use strict';
  const dateOf=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const money=value=>Number.isFinite(value)?(value/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
  const num=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:3}).format(value):'—';
  const duration=value=>{
    if(!Number.isFinite(value)||value<0)return '未知';
    const minutes=Math.round(value/60),hours=Math.floor(minutes/60),rest=minutes%60;
    return hours?`${hours} 小时${rest?` ${rest} 分钟`:''}`:`${minutes} 分钟`;
  };
  const sources={home:'家充',public:'外充',unknown:'未分类'};
  const formFields=['event_id','date','source','charge_mode_override','amount','metered_kwh','unit_price','service_fee','parking_fee','note'];
  const blank=date=>({id:'',event_id:'',date,source:'unknown',charge_mode_override:'',amount:'',metered_kwh:'',unit_price:'',service_fee:'',parking_fee:'',note:'',revision:null});
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',month=dateOf(Date.now()).slice(0,7),data=null,attempted=false,loading=false,busy=false;
    let serial=0,writeSerial=0,error='',status='',draft=blank(dateOf(Date.now())),page=0,trashPage=0,editorOpen=false;
    let pendingOpen=false,pendingPage=0,pendingReturn=null;
    let dirty=false,pendingAction=null,listFilter='all';
    const persist=()=>root.BookSession?.write(owner,'charge',{month,draft,dirty,editorOpen,attempted,pendingOpen,page,trashPage,pendingPage,listFilter});
    function protect(action){if(editorOpen&&dirty){pendingAction=action;paint();return true;}return false;}
    const context=()=>getState()?.insights_context||'';
    const valid=(token,current,identity)=>token===current&&identity===owner&&identity===context();
    const defaultDate=()=>dateOf(Date.now()).startsWith(month)?dateOf(Date.now()):month+'-01';
    const button=(label,action,disabled=false,extra='')=>`<button class="button secondary" data-ledger="${action}" ${disabled||busy?'disabled':''} ${extra}>${label}</button>`;
    function field(label,name,type='number',step='.01',extra=''){
      return `<label>${label}<input id="ledger-${name}" name="${name}" type="${type}" ${type==='number'?`min="0" step="${step}"`:''} value="${esc(draft[name])}" ${extra}></label>`;
    }
    function pendingSection(){
      const rows=data.events.filter(row=>!row.recorded),pages=Math.max(1,Math.ceil(rows.length/10));
      pendingPage=Math.min(pendingPage,pages-1);
      const title=rows.length?`本月还有 ${rows.length} 次待记账`:data.events.length?'本月充电记录已全部关联账单':'本月没有结束充电记录';
      const list=pendingOpen?rows.slice(pendingPage*10,pendingPage*10+10).map(row=>`<article class="ledger-pending-row"><div><strong>${esc(time(row.end_time))}${row.partial?' · 片段':''}</strong><span>${num(row.start_soc)}% → ${num(row.end_soc)}% · 费用待填写</span></div>${button('补记金额','pending-new',loading||editorOpen,`data-id="${esc(row.id)}" aria-label="补记 ${esc(time(row.end_time))} 的金额"`)}</article>`).join(''):'';
      const pagination=pendingOpen&&pages>1?`<div class="insight-pagination">${button('上一页待补账','pending-previous',pendingPage===0)}<span>${pendingPage+1} / ${pages}</span>${button('下一页待补账','pending-next',pendingPage+1===pages)}</div>`:'';
      return `<section class="card insight-panel" id="ledger-pending"><div class="insight-heading"><h3 id="ledger-pending-count" tabindex="-1">${title}</h3>${rows.length?button(pendingOpen?'收起待补账':'去补账','pending-toggle',loading,`aria-expanded="${pendingOpen}" aria-controls="ledger-pending-list"`):''}</div>${data.entries.some(r=>r.actual_cents===null)?`<p class="insight-note">已录账单另有 ${data.entries.filter(r=>r.actual_cents===null).length} 笔未填实际金额。</p>${button('查看金额待补账单','unknown')}`:''}${rows.length?`<p class="insight-note">按充电结束日期列出未关联记录；未关联不代表免费。已关联账单的未知费用仍需另行核对。</p><div id="ledger-pending-list" class="report-event-list" ${pendingOpen?'':'hidden'}>${list}${pagination}</div>`:''}</section>`;
    }
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected||!active())return;
      persist();
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const t=data?.totals;
      const choices=(data?.events||[]).slice();
      if(draft.event_id&&!choices.some(row=>row.id===draft.event_id)){
        const entry=data?.entries.find(row=>row.id===draft.id),linked=entry?.event;
        if(linked)choices.unshift(linked);
        else if(entry?.source_event_removed)choices.unshift({id:entry.source_event_id,removed:true,recorded:true});
      }
      node.innerHTML=`<section class="insight-hero"><div><h2>充电账本</h2>${root.recallCanReturn?.()?'<button class="button secondary" data-recall-return>返回原充电记录</button>':root.booksCanReturn?.()?'<button class="button secondary" data-books-return>返回来源页面</button>':''}<p>真实账单与估算各自列清，留空就保持未知。</p></div><span class="insight-source">手工记录 · 本机保存</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>账本月份<input id="ledger-month" type="month" value="${esc(month)}" ${busy?'disabled':''}></label>${button('读取账本','load',!owner||!month,'id="ledger-load"')}${button('撤销上一步','undo',!data?.can_undo)}</div>${!data&&!loading&&owner?'<p class="insight-note">选择查询条件后，点击“读取账本”显示结果。</p>':''}${loading?'<p role="status">正在读取账本…</p>':''}${status?`<p role="status" class="insight-note">${esc(status)}</p>`:''}${error?`<div class="notice error" role="alert">${esc(error)}</div>`:''}${!owner?'<p>连接车辆账号并取得当前车辆绑定后，可管理账本。</p>':''}${data?`<p id="ledger-range" class="insight-note">账本月份 ${data.window.start_date.slice(0,7)} · 按账单日期归期。本月有 ${data.events.length} 条结束充电记录，其中 ${data.events.filter(row=>row.recorded).length} 条已关联账单。未关联充电记录 ${data.events.filter(row=>!row.recorded).length} 条，费用尚未录入；未关联不代表免费充电。</p>`:''}</section>
        ${pendingAction?`<div class="notice info" role="status"><p>当前有未保存草稿。放弃后才能继续此操作。</p>${button('继续编辑草稿','keep')}${button('放弃草稿，继续','discard')}</div>`:''}
        ${data?`${pendingSection()}${data.entries.length?`<div class="insight-metrics report-totals"><div id="ledger-actual-total"><span>已填实际金额</span><strong>${money(t.actual_cents)} <small>元</small></strong><small>${t.actual_count} 笔账单</small></div><div><span>其余未填账单的估算</span><strong>${money(t.unbilled_estimated_cents)} <small>元</small></strong><small>${t.estimated_count} 笔估算；未并入实际金额</small></div><div><span>已录账单中费用未知</span><strong>${t.unpriced_count} <small>笔</small></strong><small>缺少实际金额或估算依据</small></div><div><span>已录桩端计量电量</span><strong>${num(t.metered_kwh)} <small>kWh</small></strong><small>${t.metered_count} 笔有计量值</small></div></div>`:''}
        <section class="card insight-panel"><div class="insight-heading"><h3>本月账单</h3>${button('新增账单','new')}</div><label>账单筛选<select id="ledger-filter" aria-label="账单筛选"><option value="all" ${listFilter==='all'?'selected':''}>全部账单</option><option value="unknown" ${listFilter==='unknown'?'selected':''}>实际金额待补</option></select></label><div id="ledger-entries"></div></section>
        ${editorOpen?`<section class="card insight-panel" id="ledger-editor"><div class="insight-heading"><h3>${draft.id?'编辑账单':'新增账单'}</h3>${button(draft.id?'取消编辑':'取消新增','cancel')}</div><form id="ledger-form" class="ledger-form" novalidate><label class="ledger-wide">关联充电记录<select id="ledger-event_id" name="event_id" aria-label="关联充电记录" ${draft.id&&data?.entries.find(row=>row.id===draft.id)?.source_event_id?'disabled':''}><option value="">手工补录，不关联记录</option>${choices.map(row=>`<option value="${esc(row.id)}" ${draft.event_id===row.id?'selected':''} ${row.recorded&&draft.event_id!==row.id?'disabled':''}>${row.removed?'已移入回收区的关联记录':`${esc(time(row.end_time))} · ${num(row.start_soc)}% → ${num(row.end_soc)}%${row.partial?' · 片段':''}${row.recorded?' · 已记账':''}`}</option>`).join('')}</select></label>${field('账单日期','date','date','', 'required')}<label>充电来源<select id="ledger-source" name="source" aria-label="充电来源">${Object.entries(sources).map(([key,label])=>`<option value="${key}" ${draft.source===key?'selected':''}>${label}</option>`).join('')}</select></label>${field('实际账单金额（元）','amount')}${field('桩端计量电量（kWh）','metered_kwh','number','.001')}<details class="ledger-wide" data-detail="ledger-extras"><summary>电价、附加费用与充电方式（可选）</summary><div class="books-extra-fields"><label>充电方式<select id="ledger-charge_mode_override" name="charge_mode_override" aria-label="充电方式"><option value="" ${!draft.charge_mode_override?'selected':''}>自动识别</option><option value="ac" ${draft.charge_mode_override==='ac'?'selected':''}>交流 AC</option><option value="dc" ${draft.charge_mode_override==='dc'?'selected':''}>直流 DC</option></select></label>${field('参考电价（元/kWh）','unit_price','number','.0001')}${field('估算附加费用（元）','service_fee')}${field('停车费（元）','parking_fee')}</div></details><label class="ledger-wide">账单备注<textarea id="ledger-note" name="note" aria-label="账单备注" maxlength="1000" rows="3">${esc(draft.note)}</textarea></label></form><p class="insight-note">实际金额填写充电费用（含电费和服务费），停车费另填，留空按 0 元。等效充电单价按实际金额 ÷ 桩端计量电量自动显示，不含停车费。参考电价与附加费用只用于独立估算；优先用桩端计量电量，缺失时才用关联事件的 SOC 电量估算。0 是明确零值，留空是未知。充电方式手动选择只覆盖本账单标签；自动识别使用关联充电记录。</p>${draft.revision!==null&&draft.revision!==data.revision?`<p class="notice error">账单已有更新，旧草稿保留。核对列表后再继续编辑。</p>${button('已核对列表，继续编辑','adopt')}`:''}<div class="insight-actions">${button(busy?'正在保存…':'保存账单','save',!owner||loading)}</div></section>`:''}
        ${data.entries.length?`<section class="card insight-panel" id="ledger-sources"><h3>充电来源占比</h3><p class="insight-note">按本月已录账单笔数计算；未分类也保留。费用仍区分实际与估算。</p><div class="report-comparison">${Object.entries(data.sources).map(([key,value])=>`<article><strong>${sources[key]} · ${value.count} 笔</strong><span>笔数占比 ${t.count?num(value.count/t.count*100)+'%':'—'}</span><span>实际 ${money(value.actual_cents)} 元</span><span>其余估算 ${money(value.unbilled_estimated_cents)} 元</span></article>`).join('')}</div></section>`:''}
        ${data.trend.some(row=>row.count>0)?`<details class="card insight-panel" data-detail="ledger-history"><summary>近六个月费用记录</summary><div><h3>近六个月费用记录</h3><div class="ledger-trend">${data.trend.map(row=>`<article><strong>${row.month}</strong><span>实际 ${money(row.actual_cents)} 元</span><span>其余估算 ${money(row.unbilled_estimated_cents)} 元</span><small>${row.count} 笔记录 · ${row.unpriced_count} 笔费用未知</small></article>`).join('')}</div></div></details>`:''}
        ${data.entries.length&&data.cost_per_km.distance_km>0?`<section class="card insight-panel"><h3>本期每公里费用参考</h3><div class="parking-row-values"><span>仅已填实际费用<strong>${num(data.cost_per_km.actual_yuan)} 元/km</strong></span><span>实际加其余估算费用<strong>${num(data.cost_per_km.including_estimates_yuan)} 元/km</strong></span></div><p class="insight-note">本期已录充电费用 ÷ 本期 ${data.cost_per_km.distance_samples} 条有效记录的 ${num(data.cost_per_km.distance_km)} km，含 ${data.cost_per_km.partial_distance_samples} 条片段，均为已观测里程。充入电量可能跨期使用，且费用和里程都可能缺记录。这是账期参考，不是每趟行程实际用电成本。</p></section>`:''}
        <div id="ledger-trash"></div>`:''}`;
      paintRows();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function paintRows(){
      if(!data||!node?.querySelector('#ledger-entries'))return;
      const entries=data.entries.filter(row=>listFilter!=='unknown'||row.actual_cents===null);
      const pages=Math.max(1,Math.ceil(entries.length/10));page=Math.min(page,pages-1);
      node.querySelector('#ledger-entries').innerHTML=entries.length?`<div class="report-event-list ledger-list">${entries.slice(page*10,page*10+10).map(row=>{
        const cost=row.actual_cents!==null?`实际充电费用 ${money(row.actual_cents)} 元`:row.estimated_cents!==null?`参考估算 ${money(row.estimated_cents)} 元`:'充电费用未知';
        const period=row.event?`${esc(time(row.event.start_time))} 至 ${esc(time(row.event.end_time))}`:`${esc(row.date)} · 未关联充电时间`;
        const elapsed=row.event?duration(row.event.duration_seconds):'未知';
        const selectedMode=row.charge_mode_override||row.event?.charge_mode;
        const mode=(selectedMode==='ac'?'交流 AC':selectedMode==='dc'?'直流 DC':'方式未知')+(row.charge_mode_override?' · 手动':'');
        const effective=row.actual_cents!==null&&Number.isFinite(row.metered_kwh)&&row.metered_kwh>0
          ?(row.actual_cents/100/row.metered_kwh).toFixed(4):null;
        return `<article data-ledger-entry="${esc(row.id)}" class="ledger-entry-row"><details class="ledger-item" data-detail="ledger-entry-${esc(row.id)}"><summary class="ledger-preview"><span class="ledger-preview-time"><strong>${period}</strong><small>时长 ${elapsed}</small><small class="ledger-mode">${mode}</small></span><span>电量 <strong>${num(row.metered_kwh)} kWh</strong></span><span>${cost}</span></summary><div class="ledger-detail"><p>${sources[row.source]} · ${row.event?'关联充电记录':row.source_event_removed?'关联记录已移入回收区':'手工补录'}</p><div class="parking-row-values"><span>停车费<strong>${money(row.parking_fee_cents??0)} 元</strong></span>${effective!==null?`<span>等效充电单价<strong>${effective} 元/kWh</strong></span>`:''}${row.estimated_cents!==null?`<span>参考估算<strong>${money(row.estimated_cents)} 元</strong></span><span>估算依据<strong>${{metered_price:'计量电量 × 电价 + 附加费用',soc_price:'SOC 电量估算 × 电价 + 附加费用'}[row.estimate_basis]||'依据不足，不计算'}</strong></span>`:''}</div>${row.event?`<p class="insight-note">事件电量估算 ${num(row.event.estimated_kwh)} kWh · 事件记录容量 ${num(row.event.battery_capacity_kwh)} kWh</p>`:row.source_event_removed?'<p class="insight-note">关联充电记录已移入回收区；人工填写内容保留，SOC 自动估算已停用。</p>':''}${row.note?`<p class="ledger-note">${esc(row.note)}</p>`:''}<div class="insight-actions">${button('删除账单','delete',false,`data-id="${esc(row.id)}"`)}</div></div></details>${button('编辑账单','edit',false,`data-id="${esc(row.id)}"`)}</article>`;
      }).join('')}</div><div class="insight-pagination">${button('上一页账单','previous',page===0)}<span>${page+1} / ${pages}</span>${button('下一页账单','next',page+1===pages)}</div>`:`<p class="insight-empty">${listFilter==='unknown'&&data.entries.length?'本月没有实际金额待补账单。':'本月还没有账单。可新增手工账单，或从待补充电记录开始。未记账不代表没有支出。'}</p>`;
      const trashPages=Math.max(1,Math.ceil(data.trash.length/10));trashPage=Math.min(trashPage,trashPages-1);
      node.querySelector('#ledger-trash').innerHTML=data.trash.length?`<section class="card insight-panel"><h3>已删除账单 · 可恢复</h3><div class="ledger-trash-list">${data.trash.slice(trashPage*10,trashPage*10+10).map(row=>`<div><span>${row.date} · ${sources[row.source]} · 实际 ${money(row.actual_cents)} 元</span>${button('恢复账单','restore',false,`data-id="${esc(row.id)}"`)}</div>`).join('')}</div><div class="insight-pagination">${button('上一页已删除','trash-previous',trashPage===0)}<span>${trashPage+1} / ${trashPages}</span>${button('下一页已删除','trash-next',trashPage+1===trashPages)}</div></section>`:'';
    }
    async function load(preservePages=false){
      if(!owner||!month)return;
      const identity=owner,token=++serial;loading=true;attempted=true;error='';paint();
      try{
        const result=await request('/api/insights/ledger?date='+encodeURIComponent(month+'-01'));
        if(!valid(token,serial,identity))return false;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新加载。');
        data=result;if(!preservePages){page=0;trashPage=0;pendingPage=0;}return true;
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
      const payload={...(action==='save'?draft:{}),action,id:action==='save'?draft.id:id,revision:action==='save'?(draft.revision??data.revision):data.revision,context:owner};
      let returnScroll=null;
      const restore=()=>{if(returnScroll!==null&&active()){root.scrollTo({top:returnScroll,behavior:'instant'});node.querySelector('#ledger-pending-count')?.focus({preventScroll:true});}};
      const finish=root.RefreshView?.guard?root.RefreshView.guard(restore):restore;
      busy=true;error='';status='';paint();
      try{
        const result=await request('/api/insights/ledger',payload);
        if(!valid(token,writeSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新加载。');
        data.revision=result.revision;data.can_undo=result.can_undo;
        status={save:'账单已保存。',delete:'账单已删除，可在下方恢复或撤销。',restore:'账单已恢复。',undo:'上一步已撤销。'}[action];
        const sameMonth=action!=='save'||month===result.saved_date.slice(0,7);
        if(action==='save'){
          returnScroll=sameMonth?pendingReturn:null;pendingReturn=null;
          month=result.saved_date.slice(0,7);draft=blank(defaultDate());editorOpen=false;dirty=false;
        }
        else if(action==='delete'&&draft.id===id)draft=blank(defaultDate());
        const refreshed=await load(sameMonth);
        if(!refreshed&&valid(token,writeSerial,identity))status+=' 列表尚未刷新，请重新读取账本核对。';
      }catch(failure){if(valid(token,writeSerial,identity))error=failure.message+' 填写内容保留；请重新读取账本核对后再操作。';}
      finally{if(valid(token,writeSerial,identity)){busy=false;paint();finish();}}
    }
    function edit(id,force=false){
      if(!force&&protect(()=>edit(id,true)))return;
      const row=data.entries.find(row=>row.id===id);if(!row)return;
      draft={id:row.id,event_id:row.source_event_id||'',date:row.date,source:row.source,
        amount:row.actual_cents===null?'':(row.actual_cents/100).toFixed(2),metered_kwh:row.metered_kwh??'',
        unit_price:row.unit_price??'',service_fee:row.service_fee_cents===null?'':(row.service_fee_cents/100).toFixed(2),
        parking_fee:((row.parking_fee_cents??0)/100).toFixed(2),charge_mode_override:row.charge_mode_override||'',note:row.note,revision:data.revision};
      dirty=false;
      pendingReturn=null;editorOpen=true;error='';paint();openEditor();
    }
    function openEditor(focus='date'){
      node.querySelector('#ledger-editor')?.scrollIntoView({block:'start'});
      node.querySelector('#ledger-'+focus)?.focus({preventScroll:true});
    }
    let tripRevision,chargeRevision;
    function mount(container){
      const changed=owner!==context(),recordsChanged=!busy&&(tripRevision!==getState()?.trip_records_revision||chargeRevision!==getState()?.charge_records_revision),remount=node!==container;node=container;
      if(changed||recordsChanged){tripRevision=getState()?.trip_records_revision;chargeRevision=getState()?.charge_records_revision;}
      if(changed){owner=context();data=null;attempted=false;loading=false;busy=false;serial++;writeSerial++;error='';status='';draft=blank(defaultDate());editorOpen=false;pendingOpen=false;pendingPage=0;pendingReturn=null;dirty=false;pendingAction=null;
        const saved=root.BookSession?.read(owner,'charge');
        if(saved){month=saved.month||month;draft={...blank(defaultDate()),...saved.draft};dirty=!!saved.dirty;editorOpen=!!saved.editorOpen;pendingOpen=!!saved.pendingOpen;page=saved.page||0;trashPage=saved.trashPage||0;pendingPage=saved.pendingPage||0;listFilter=saved.listFilter==='unknown'?'unknown':'all';load(true);}else load();
      }
      else if(recordsChanged&&attempted){
        if(editorOpen){serial++;loading=false;status='行程或充电记录已变化；填写内容保留，请读取账本核对后再保存。';}
        else load(true);
      }
      if(changed||recordsChanged||remount)paint();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;
      const el=event.target;
      if(event.type==='input'&&el.id==='ledger-month'){if(month!==el.value){month=el.value;serial++;data=null;attempted=loading=false;error=status='';page=trashPage=pendingPage=0;pendingOpen=false;pendingReturn=null;paint();}return true;}
      if((event.type==='input'||event.type==='change')&&formFields.includes(el.name)){
        if(draft.revision===null&&data)draft.revision=data.revision;dirty=true;draft[el.name]=el.value;
        if(el.name==='event_id'){
          const row=data?.events.find(row=>row.id===el.value);
          if(row){draft.date=dateOf(row.end_time);node.querySelector('#ledger-date').value=draft.date;}
        }
        persist();return true;
      }
      if(event.type==='change'&&el.id==='ledger-filter'){setFilter(el.value);return true;}
      if(event.type!=='click')return false;
      const target=el.closest('[data-ledger]');if(!target||target.disabled)return false;
      if(['new','cancel','pending-new'].includes(target.dataset.ledger)&&protect(()=>{dirty=false;const next=node.querySelector(`[data-ledger="${target.dataset.ledger}"]${target.dataset.id?`[data-id="${target.dataset.id}"]`:''}`);if(next)handle({type:'click',target:next});}))return true;
      switch(target.dataset.ledger){
        case 'keep':pendingAction=null;paint();break;
        case 'discard':{const action=pendingAction;pendingAction=null;dirty=false;action?.();break;}
        case 'adopt':draft.revision=data.revision;error='';paint();break;
        case 'unknown':setFilter('unknown');node.querySelector('#ledger-entries')?.scrollIntoView({block:'start'});break;
        case 'load':load();break;
        case 'new':dirty=false;pendingReturn=null;draft=blank(defaultDate());editorOpen=true;error='';paint();openEditor();break;
        case 'cancel':dirty=false;draft=blank(defaultDate());editorOpen=false;error='';paint();if(pendingReturn!==null)root.scrollTo({top:pendingReturn,behavior:'instant'});pendingReturn=null;break;
        case 'pending-toggle':pendingOpen=!pendingOpen;paint();break;
        case 'pending-new':{
          const row=data?.events.find(row=>row.id===target.dataset.id&&!row.recorded);
          if(!row||loading||editorOpen)return true;
          pendingReturn=root.scrollY;draft={...blank(dateOf(row.end_time)),event_id:row.id};
          editorOpen=true;error='';paint();openEditor('amount');break;
        }
        case 'pending-previous':pendingPage--;paint();break;
        case 'pending-next':pendingPage++;paint();break;
        case 'save':mutate('save');break;
        case 'delete':case 'restore':case 'undo':mutate(target.dataset.ledger,target.dataset.id);break;
        case 'edit':edit(target.dataset.id);break;
        case 'previous':page--;paintRows();break;
        case 'next':page++;paintRows();break;
        case 'trash-previous':trashPage--;paintRows();break;
        case 'trash-next':trashPage++;paintRows();break;
      }
      persist();return true;
    }
    async function openEvent(eventId,date){
      if(protect(()=>openEvent(eventId,date)))return;
      month=date.slice(0,7);const identity=context();
      if(!await load()||identity!==context()||!active())return;
      let bill=data.entries.find(row=>row.source_event_id===eventId);
      const choice=data.events.find(row=>row.id===eventId);
      if(!bill&&choice?.recorded&&choice.bill_date){
        month=choice.bill_date.slice(0,7);
        if(!await load()||identity!==context()||!active())return;
        bill=data.entries.find(row=>row.source_event_id===eventId);
      }
      if(bill)edit(bill.id);
      else if(!choice?.recorded&&data.events.some(row=>row.id===eventId)){draft={...blank(date),event_id:eventId};editorOpen=true;error='';paint();openEditor('amount');}
    }
    async function openDate(date){
      const next=date.slice(0,7);
      if(month!==next){month=next;serial++;data=null;pendingOpen=false;pendingPage=0;}
      await load();
    }
    function setFilter(value){listFilter=value==='unknown'?'unknown':'all';page=0;paint();}
    return {mount,handle,openEvent,openDate,setFilter};
  }
  root.ChargeLedgerPage={create};
})(window);
