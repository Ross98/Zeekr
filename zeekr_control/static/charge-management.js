(function(root){
  'use strict';
  const time=value=>Number.isFinite(value)?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)):'未知';
  const number=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value):'未知';
  function create({getState,getDate,request,escape:esc,active,changed}){
    let node=null,owner='',outerDate='',start='',end='',status='active',data=null,preview=null;
    let selected=new Set(),cursor=null,previous=[],loading=false,busy=false,error='',message='',serial=0,seenRevision;
    const context=()=>getState()?.insights_context||'';
    const valid=token=>token===serial&&owner===context()&&outerDate===getDate()&&active()&&node?.isConnected;
    const button=(label,action,disabled=false)=>`<button type="button" class="button secondary" data-charge-manage="${action}" ${disabled?'disabled':''}>${label}</button>`;
    const summary=row=>`<strong>${esc(time(row.start_time))} → ${esc(time(row.end_time))}</strong><span>SOC ${esc(number(row.start_soc))}% → ${esc(number(row.end_soc))}% · ${row.partial?'片段记录':'完整记录'} · ${esc(number(row.estimated_kwh))} kWh（估算）</span><small>${row.charge_mode==='ac'?'AC':row.charge_mode==='dc'?'DC':'模式未知'} · ${esc(number(row.duration_seconds===null?null:row.duration_seconds/60))} 分钟${row.removed_at?` · 移入 ${esc(time(row.removed_at))}`:''}</small>${row.issue?`<small class="unknown">${esc(row.issue)} 记录时间 ${esc(time(row.recorded_at))}</small>`:''}`;
    function reset(){serial++;data=preview=null;selected.clear();cursor=null;previous=[];loading=busy=false;error=message='';}
    function paint(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const action=status==='trash'?'restore':'trash',label=action==='restore'?'恢复':'移入回收区';
      const stale=data&&Number.isInteger(getState()?.charge_records_revision)&&data.revision<getState().charge_records_revision;
      const linked=preview?.linked_bills||[];
      node.innerHTML=`<section class="card trip-manage-panel" aria-labelledby="charge-manage-title"><div class="local-trip-title"><h2 id="charge-manage-title">管理充电记录</h2><span class="subtle">仅管理自动采集的已结束事件</span></div>
        <p class="subtle">错误记录移入回收区后，从充电详情、统计、趋势、日历、自动洞察、对比和账单关联候选中排除。原始事件与采样保留，可恢复。</p>
        <div class="trip-manage-filters"><label>开始日期<input id="charge-manage-start" type="date" value="${esc(start)}" ${busy?'disabled':''}></label><label>结束日期<input id="charge-manage-end" type="date" value="${esc(end)}" ${busy?'disabled':''}></label><label>记录状态<select id="charge-manage-status" ${busy?'disabled':''}><option value="active" ${status==='active'?'selected':''}>正常记录</option><option value="trash" ${status==='trash'?'selected':''}>回收区</option></select></label>${button('查询管理充电记录','load',loading||busy||!owner||!start||!end)}</div>
        ${!owner?'<p>连接车辆账号并取得当前车辆缓存后，可管理记录。</p>':''}${error?`<p class="notice error" role="alert">${esc(error)}</p>`:''}${message?`<p class="notice info" role="status">${esc(message)}</p>`:''}${stale?'<p class="unknown">充电记录已变化，请重新读取再操作。</p>':''}${!data&&!loading&&owner?'<p class="subtle" role="status">选择日期和状态，点击查询后显示记录。</p>':''}${loading?'<p role="status">正在读取充电记录…</p>':''}
        ${data?`<div class="trip-manage-actions">${button('选择本页','all',busy||loading||!data.items.length)}${button('清空选择','clear',busy||!selected.size)}<span role="status">已选 ${selected.size} 条 / 最多 100 条</span>${button('预览'+label,'preview',busy||loading||!selected.size||!!preview||stale)}</div><div class="trip-manage-rows">${data.items.map(row=>`<label class="trip-manage-row"><input type="checkbox" data-charge-record="${esc(row.id)}" aria-label="选择 ${esc(time(row.end_time))} 的充电记录" ${selected.has(row.id)?'checked':''} ${busy||loading||preview?'disabled':''}><span>${summary(row)}</span></label>`).join('')||`<p class="subtle">这段日期没有${status==='trash'?'回收区记录':'正常充电记录'}。</p>`}</div><div class="local-trip-pagination">${button('上一页充电记录','previous',busy||loading||!!preview||!previous.length)}<span>第 ${previous.length+1} 页</span>${button('下一页充电记录','next',busy||loading||!!preview||!data.next_cursor)}</div>`:''}
        ${preview?`<section id="charge-manage-preview" class="trip-manage-preview" tabindex="-1"><h3>确认${preview.action==='trash'?'移入回收区':'恢复'} ${preview.count} 条充电记录</h3><p>${preview.action==='trash'?'记录将退出全部自动充电统计；尚未发送的通知会取消。':'记录将重新计入统计；不会补发通知。'} 原始事件和采样不变。</p>${linked.length?`<p class="notice info">发现 ${linked.length} 条关联手工账单。${preview.with_linked_bills?'本次将同时处理这些账单。':'默认保留人工填写内容，并停用被删除事件的自动估算。'}</p>`:''}<div class="trip-manage-preview-list">${preview.items.map(row=>`<article>${summary(row)}</article>`).join('')}</div><div class="trip-manage-actions">${button('取消预览','cancel',busy)}${linked.length&&!preview.with_linked_bills?button(`同时${preview.action==='trash'?'移入':'恢复'}关联账单`,'with-bills',busy):''}${button(busy?'正在保存…':'确认'+(preview.action==='trash'?'移入回收区':'恢复'),'execute',busy)}</div></section>`:''}
      </section>`;
      if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    async function load(){
      if(!owner||!start||!end)return;const token=++serial;loading=true;error='';preview=null;paint();
      try{const result=await request(`/api/charging/manage?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&status=${status}${cursor?'&cursor='+encodeURIComponent(cursor):''}`);if(!valid(token))return;if(result.context!==owner)throw Error('账号或车辆已切换，请重新读取。');if(data&&data.revision!==result.revision){selected.clear();message='充电记录已变化，请重新选择。';}data=result;if(Number.isInteger(getState()?.charge_records_revision)&&result.revision>getState().charge_records_revision)changed(result.revision);}
      catch(failure){if(valid(token)){error=failure.message;data=null;}}finally{if(valid(token)){loading=false;paint();}}
    }
    async function makePreview(withBills=false){
      if(busy||!data||!selected.size)return;const token=++serial;busy=true;error='';paint();
      try{const body={action:status==='trash'?'restore':'trash',ids:[...selected],revision:data.revision,with_linked_bills:withBills};if(withBills)body.ledger_revision=preview.ledger_revision;const result=await request('/api/charging/manage/preview',{...body,context:owner});if(!valid(token))return;preview=result;busy=false;paint();node.querySelector('#charge-manage-preview')?.focus({preventScroll:true});}
      catch(failure){if(valid(token))error=failure.message;}finally{if(valid(token)){busy=false;paint();}}
    }
    async function execute(){
      if(busy||!preview)return;const token=++serial;busy=true;error='';paint();
      try{const result=await request('/api/charging/manage/execute',{token:preview.token,context:owner});if(!valid(token))return;selected.clear();preview=data=null;cursor=null;previous=[];busy=false;message=`已${result.action==='trash'?'移入回收区':'恢复'} ${result.count} 条充电记录。相关统计已更新。`;changed(result.revision);await load();}
      catch(failure){if(valid(token)){error=failure.message;preview=null;}}finally{if(valid(token)){busy=false;paint();}}
    }
    function mount(container){const resetNeeded=owner!==context()||outerDate!==getDate(),remount=node!==container,revisionChanged=seenRevision!==getState()?.charge_records_revision;seenRevision=getState()?.charge_records_revision;node=container;if(resetNeeded){reset();owner=context();outerDate=getDate();start=end=outerDate;status='active';paint();}else if(remount||revisionChanged)paint();}
    function suspend(){reset();owner='';outerDate='';node=null;}
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;const el=event.target;
      if(event.type==='input'&&['charge-manage-start','charge-manage-end'].includes(el.id)){if(el.id.endsWith('start'))start=el.value;else end=el.value;reset();paint();return true;}
      if(event.type==='change'){if(el.id==='charge-manage-status'){status=el.value;reset();paint();return true;}if(el.dataset.chargeRecord){if(el.checked&&selected.size>=100){el.checked=false;error='每次最多选择 100 条充电记录。';}else if(el.checked)selected.add(el.dataset.chargeRecord);else selected.delete(el.dataset.chargeRecord);preview=null;paint();return true;}}
      if(event.type!=='click')return false;const target=el.closest('[data-charge-manage]');if(!target||target.disabled)return false;
      switch(target.dataset.chargeManage){case 'load':cursor=null;previous=[];load();break;case 'all':for(const row of data.items){if(selected.size<100)selected.add(row.id);}preview=null;paint();break;case 'clear':selected.clear();preview=null;paint();break;case 'cancel':preview=null;paint();break;case 'preview':makePreview();break;case 'with-bills':makePreview(true);break;case 'execute':execute();break;case 'next':previous.push(cursor);cursor=data.next_cursor;load();break;case 'previous':cursor=previous.pop();load();break;}return true;
    }
    return {mount,handle,suspend};
  }
  root.ChargeManagement={create};
})(window);
