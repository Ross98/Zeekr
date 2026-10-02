(function(root){
  'use strict';
  const time=value=>Number.isFinite(value)?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)):'未知';
  const number=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value):'未知';
  function create({getState,getDate,request,escape:esc,active,changed}){
    let node=null,owner='',outerDate='',start='',end='',status='active',data=null,preview=null;
    let selected=new Set(),cursor=null,previous=[],loading=false,busy=false,error='',message='',serial=0,seenRevision;
    const context=()=>getState()?.insights_context||'';
    const valid=token=>token===serial&&owner===context()&&outerDate===getDate()&&active()&&node?.isConnected;
    const button=(label,action,disabled=false)=>`<button type="button" class="button secondary" data-trip-manage="${action}" ${disabled?'disabled':''}>${label}</button>`;
    const summary=row=>`<strong>${esc(time(row.start_time))} → ${esc(time(row.end_time))}</strong><span>${esc(number(row.distance_km))} km · ${row.partial?'片段记录':'完整记录'} · ${esc(number(row.duration_seconds===null?null:row.duration_seconds/60))} 分钟</span><small>SOC ${esc(number(row.start_soc))}% → ${esc(number(row.end_soc))}%${row.removed_at?` · 移入 ${esc(time(row.removed_at))}`:''}</small>${row.issue?`<small class="unknown">${esc(row.issue)} 记录时间 ${esc(time(row.recorded_at))}</small>`:''}`;
    function reset(){serial++;data=preview=null;selected.clear();cursor=null;previous=[];loading=busy=false;error=message='';}
    function paint(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const action=status==='trash'?'restore':'trash',label=action==='restore'?'恢复':'移入回收区';
      const stale=data&&Number.isInteger(getState()?.trip_records_revision)&&data.revision<getState().trip_records_revision;
      node.innerHTML=`<section class="card trip-manage-panel" aria-labelledby="trip-manage-title"><div class="local-trip-title"><h2 id="trip-manage-title">管理行程</h2><span class="subtle">仅管理本地已结束记录</span></div>
        <p class="subtle">错误行程移入回收区后，从行程列表和相关统计中排除。原始采样、行程摘要和标签保留，随时可恢复。按结束日期筛选，每次最多查询 366 天。</p>
        <div class="trip-manage-filters"><label>开始日期<input id="trip-manage-start" type="date" value="${esc(start)}" ${busy?'disabled':''}></label><label>结束日期<input id="trip-manage-end" type="date" value="${esc(end)}" ${busy?'disabled':''}></label><label>记录状态<select id="trip-manage-status" ${busy?'disabled':''}><option value="active" ${status==='active'?'selected':''}>正常记录</option><option value="trash" ${status==='trash'?'selected':''}>回收区</option></select></label>${button('查询管理行程','load',loading||busy||!owner||!start||!end)}</div>
        ${!owner?'<p>连接车辆账号并取得当前车辆缓存后，可管理记录。</p>':''}
        ${error?`<p class="notice error" role="alert">${esc(error)}</p>`:''}${message?`<p class="notice info" role="status">${esc(message)}</p>`:''}
        ${stale?'<p class="unknown">行程记录已变化。当前选择和预览保留，请重新读取再操作。</p>':''}
        ${!data&&!loading&&owner?'<p class="subtle" role="status">选择日期和状态，点击查询后显示记录。</p>':''}${loading?'<p role="status">正在读取行程…</p>':''}
        ${data?`<div class="trip-manage-actions">${button('选择本页','all',busy||loading||!data.items.length)}${button('清空选择','clear',busy||!selected.size)}<span role="status">已选 ${selected.size} 条 / 最多 100 条</span>${button('预览'+label,'preview',busy||loading||!selected.size||!!preview||stale)}</div>
        <div class="trip-manage-rows">${data.items.map(row=>`<label class="trip-manage-row"><input type="checkbox" id="trip-record-${esc(row.id)}" data-trip-record="${esc(row.id)}" aria-label="选择 ${esc(time(row.start_time))} 的行程" ${selected.has(row.id)?'checked':''} ${busy||loading||preview?'disabled':''}><span>${summary(row)}</span></label>`).join('')||`<p class="subtle">这段日期没有${status==='trash'?'回收区记录':'正常行程'}。</p>`}</div>
        <div class="local-trip-pagination">${button('上一页行程','previous',busy||loading||!!preview||!previous.length)}<span>第 ${previous.length+1} 页</span>${button('下一页行程','next',busy||loading||!!preview||!data.next_cursor)}</div>`:''}
        ${preview?`<section id="trip-manage-preview" class="trip-manage-preview" aria-labelledby="trip-manage-preview-title" tabindex="-1"><h3 id="trip-manage-preview-title">确认${preview.action==='trash'?'移入回收区':'恢复'} ${preview.count} 条行程</h3><p>${preview.action==='trash'?'这些行程将退出相关统计；尚未发送的行程通知会取消。':'这些行程将重新计入相关统计；不会补发行程通知。'} 已发送通知保留原内容。全天采样不变。</p><div class="trip-manage-preview-list">${preview.items.map(row=>`<article>${summary(row)}</article>`).join('')}</div><p class="subtle">预览有效至 ${esc(time(preview.expires_at))}。核对后确认。</p><div class="trip-manage-actions">${button('取消预览','cancel',busy)}${button(busy?'正在保存…':'确认'+(preview.action==='trash'?'移入回收区':'恢复'),'execute',busy)}</div></section>`:''}
      </section>`;
      if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    async function load(){
      if(!owner||!start||!end)return;
      const token=++serial;loading=true;error='';preview=null;paint();
      try{
        const result=await request(`/api/trips/manage?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&status=${status}${cursor?'&cursor='+encodeURIComponent(cursor):''}`);
        if(!valid(token))return;
        if(result.context!==owner)throw Error('账号或车辆已切换，请重新读取。');
        if(data&&data.revision!==result.revision){selected.clear();message='行程记录已变化，请重新选择。';}
        data=result;
        if(Number.isInteger(getState()?.trip_records_revision)&&result.revision>getState().trip_records_revision)changed(result.revision);
      }catch(failure){if(valid(token)){error=failure.message;data=null;}}
      finally{if(valid(token)){loading=false;paint();}}
    }
    async function mutate(operation){
      if(busy||!data||operation==='preview'&&!selected.size||operation==='execute'&&!preview)return;
      const token=++serial;busy=true;error='';message='';paint();
      try{
        const body=operation==='preview'?{action:status==='trash'?'restore':'trash',ids:[...selected],revision:data.revision}:{token:preview.token};
        const result=await request('/api/trips/manage/'+operation,{...body,context:owner});
        if(!valid(token))return;
        if(result.context!==owner)throw Error('账号或车辆已切换，请重新读取。');
        if(operation==='preview'){preview=result;busy=false;paint();node.querySelector('#trip-manage-preview')?.focus({preventScroll:true});node.querySelector('#trip-manage-preview')?.scrollIntoView({block:'nearest'});}
        else{
          selected.clear();preview=null;data=null;cursor=null;previous=[];busy=false;
          message=`已${result.action==='trash'?'移入回收区':'恢复'} ${result.count} 条行程。相关统计已更新。`;
          changed(result.revision);await load();
        }
      }catch(failure){if(valid(token)){error=failure.message;if(operation==='execute')preview=null;}}
      finally{if(valid(token)){busy=false;paint();}}
    }
    function mount(container){
      const resetNeeded=owner!==context()||outerDate!==getDate(),remount=node!==container;
      const revisionChanged=seenRevision!==getState()?.trip_records_revision;
      seenRevision=getState()?.trip_records_revision;node=container;
      if(resetNeeded){reset();owner=context();outerDate=getDate();start=end=outerDate;status='active';paint();}
      else if(remount||revisionChanged)paint();
    }
    function suspend(){reset();owner='';outerDate='';node=null;}
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;
      const el=event.target;
      if(event.type==='input'&&['trip-manage-start','trip-manage-end'].includes(el.id)){
        if(el.id.endsWith('start'))start=el.value;else end=el.value;
        reset();paint();return true;
      }
      if(event.type==='change'){
        if(el.id==='trip-manage-status'){status=el.value;reset();paint();return true;}
        if(el.dataset.tripRecord){
          if(el.checked&&selected.size>=100){el.checked=false;error='每次最多选择 100 条行程。';}
          else if(el.checked)selected.add(el.dataset.tripRecord);else selected.delete(el.dataset.tripRecord);
          preview=null;paint();return true;
        }
      }
      if(event.type!=='click')return false;
      const target=el.closest('[data-trip-manage]');if(!target||target.disabled)return false;
      switch(target.dataset.tripManage){
        case 'load':cursor=null;previous=[];load();break;
        case 'all':for(const row of data.items){if(selected.size<100)selected.add(row.id);}preview=null;paint();break;
        case 'clear':selected.clear();preview=null;paint();break;
        case 'cancel':preview=null;paint();break;
        case 'preview':mutate('preview');break;
        case 'execute':mutate('execute');break;
        case 'next':previous.push(cursor);cursor=data.next_cursor;load();break;
        case 'previous':cursor=previous.pop();load();break;
      }
      return true;
    }
    return {mount,handle,suspend};
  }
  root.TripManagement={create};
})(window);
