(function(root){
  'use strict';
  const beijingInput=stamp=>new Date(stamp+8*3600000).toISOString().slice(0,19);
  const blank=()=>({id:'',title:'',action_text:'',action_time:beijingInput(Date.now()),note:''});
  const warningLabels={action_not_bracketed:'动作时间不在两条采集时间之间，不能据此前后关系推断影响。',vehicle_time_unknown:'样本车辆时间未知。',vehicle_time_not_advanced:'车辆时间没有推进，可能只是重复或修订。',flagged_samples:'样本有陈旧、时间异常等标记。',wide_sample_gap:'两个采集样本相隔超过十分钟，期间可能有其他变化。'};
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',data=null,attempted=false,loading=false,busy=false,serial=0,detailSerial=0,writeSerial=0;
    let draft=blank(),dirty=false,comparison=null,chosen=new Set(),query='',fieldPage=0,page=0,recordFilter='active',error='',status='';
    const today=()=>beijingInput(Date.now()).slice(0,10);
    let dates={before:today(),after:today()},lists={before:null,after:null},selected={before:'',after:''};
    let sampleLoading={before:false,after:false},sampleSerial={before:0,after:0},sampleError={before:'',after:''};
    const context=()=>getState()?.insights_context||'';
    const valid=(token,current,identity)=>token===current&&identity===owner&&context()===identity;
    const button=(label,action,disabled=false,extra='')=>`<button class="button secondary" data-lab="${action}" ${disabled||busy?'disabled':''} ${extra}>${label}</button>`;
    const actionAt=()=>Date.parse(draft.action_time+'+08:00');
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">车辆参数实验室</span><h2>记录动作，留住变化线索</h2><p>前后样本、实际动作、研究备注，放进同一条记录。</p></div><span class="insight-source">研究记录 · 不自动核验</span></section>
        <section class="card insight-panel"><div class="insight-toolbar">${button('读取实验记录','load',!owner||loading)}${button('撤销实验操作','undo',!data?.can_undo)}${button('新建实验','new')}</div>${loading?'<p role="status">正在读取记录…</p>':''}${status?`<p role="status" class="insight-note">${esc(status)}</p>`:''}${error?`<p role="alert" class="notice error">${esc(error)}</p>`:''}${!owner?'<p>等待当前账号的车辆缓存后，可管理实验。</p>':!data?'<p>点击“读取实验记录”加载记录后，可保存实验。</p>':''}<p class="insight-note">这里只记录你实际做过的动作，不操作车辆。看到变化不代表动作导致变化，也不会更改参数核验状态或提醒能力。</p></section>
        <section class="card insight-panel"><h3>${draft.id?'编辑实验描述':'选择前后观测'}</h3>${draft.id?'<p class="insight-note">保存后的样本与字段保留原记录；更换样本或增加字段，请新建实验。</p>':`<div class="charge-selectors">${['before','after'].map(side=>{
          const label=side==='before'?'前':'后',list=lists[side];
          return `<div><div class="insight-toolbar"><label>${label}样本日期<input id="lab-date-${side}" type="date" value="${dates[side]}" ${busy?'disabled':''}></label>${button('读取'+label+'样本','samples',!owner||sampleLoading[side],`data-side="${side}"`)}</div><label>${label}样本<select id="lab-sample-${side}" aria-label="${label}样本" ${busy?'disabled':''}><option value="">选择${label}样本</option>${(list?.items||[]).map(r=>`<option value="${esc(r.key)}" ${selected[side]===r.key?'selected':''}>采集 ${esc(time(r.observed_at))} · 车辆 ${esc(time(r.state_time))}</option>`).join('')}</select></label><p class="insight-note">${sampleLoading[side]?'正在读取…':list?list.date+' · 已载入 '+list.items.length+' 条':'选择日期读取归档'}${list?.next_cursor?'，还有更多':''}</p>${list?.next_cursor?button('加载更多'+label+'样本','more',sampleLoading[side],`data-side="${side}"`):''}${sampleError[side]?`<p role="alert">${esc(sampleError[side])}</p>`:''}</div>`;
        }).join('')}</div><div class="insight-actions">${button('比较实验样本','compare',!selected.before||!selected.after||selected.before===selected.after||sampleLoading.before||sampleLoading.after)}</div>`}
        <form id="lab-form" class="ledger-form" novalidate><label>实验名称<input id="lab-title" type="text" required maxlength="80" value="${esc(draft.title)}" ${busy?'disabled':''}></label><label>动作时间（北京时间）<input id="lab-action-time" type="datetime-local" step="1" required value="${esc(draft.action_time)}" ${busy?'disabled':''}></label><label class="ledger-wide">实际动作<input id="lab-action-text" type="text" required maxlength="300" value="${esc(draft.action_text)}" ${busy?'disabled':''}></label><label class="ledger-wide">研究备注<textarea id="lab-note" aria-label="研究备注" maxlength="2000" rows="4" ${busy?'disabled':''}>${esc(draft.note)}</textarea></label></form><div id="lab-warnings"></div></section>
        <div id="lab-comparison">${comparison?`<section class="card insight-panel"><div class="insight-heading"><h3>前后变化 · 研究线索</h3><span class="insight-badge">${draft.id?'保存时的观测摘录':'当前所选样本'}</span></div><p class="insight-note">前样本采集 ${esc(time(comparison.before.observed_at))}，车辆时间 ${esc(time(comparison.before.state_time))}<br>后样本采集 ${esc(time(comparison.after.observed_at))}，车辆时间 ${esc(time(comparison.after.state_time))}<br>${draft.id?'摘录保留原值显示与当时解释；原归档被清理后仍可回看。':'共 '+comparison.changes.length+' 项安全字段变化；最多保存其中 40 项。'} 所有内容仍是研究线索，不是已核验语义。</p><div class="insight-toolbar"><label>筛选变化字段<input id="lab-search" type="search" value="${esc(query)}"></label>${button('选择筛选中的前 40 项','select-filter',!!draft.id)}${button('清空字段选择','clear-fields',!!draft.id)}<span id="lab-chosen-count"></span></div><div id="lab-fields"></div><div class="insight-actions">${button('保存实验记录','save',!owner||!data||loading)}</div></section>`:''}</div>
        ${data?`<section class="card insight-panel"><div class="insight-heading"><h3>实验记录</h3><label>实验记录状态<select id="lab-record-filter" aria-label="实验记录状态"><option value="active" ${recordFilter==='active'?'selected':''}>保留的记录</option><option value="deleted" ${recordFilter==='deleted'?'selected':''}>已删除记录</option></select></label></div><p class="insight-note">本车最多保存 200 条实验（含可恢复记录），按最近修改排列。</p><div id="lab-records"></div></section>`:''}`;
      paintChanges();paintRecords();paintWarnings();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function paintWarnings(){
      const el=node?.querySelector('#lab-warnings');if(!el||!comparison)return;
      const a=comparison.before,b=comparison.after,warnings=[];
      if(!(a.observed_at<=actionAt()&&actionAt()<=b.observed_at))warnings.push('action_not_bracketed');
      if(a.state_time===null||b.state_time===null)warnings.push('vehicle_time_unknown');else if(b.state_time<=a.state_time)warnings.push('vehicle_time_not_advanced');
      if(a.flags.length||b.flags.length)warnings.push('flagged_samples');
      if(b.observed_at-a.observed_at>600000)warnings.push('wide_sample_gap');
      el.innerHTML=warnings.map(code=>`<p class="insight-note insight-warning">${warningLabels[code]}</p>`).join('');
    }
    const filtered=()=>comparison?.changes.filter(f=>(f.path+' '+f.name+' '+f.group).toLowerCase().includes(query.toLowerCase()))||[];
    function paintChanges(){
      const el=node?.querySelector('#lab-fields');if(!el||!comparison)return;
      const fields=filtered(),pages=Math.max(1,Math.ceil(fields.length/12));fieldPage=Math.min(fieldPage,pages-1);
      el.innerHTML=`<div class="insight-diff lab-diff">${fields.slice(fieldPage*12,fieldPage*12+12).map(f=>`<article data-lab-field="${esc(f.path)}"><div><label class="lab-field-check"><input type="checkbox" data-lab-path="${esc(f.path)}" ${chosen.has(f.path)?'checked':''} ${draft.id||busy?'disabled':''}>${esc(f.name)}</label><small>${esc(f.path)}</small><button class="text-link" data-open-research="${esc(f.path)}">查看历史与场景</button>${f.display_limited?'<small>显示已简化，完整值确有差异。</small>':''}</div>${['before','after'].map(side=>`<div><span>${side==='before'?'前':'后'}</span><b>${esc(f[side].value)}</b><small>原值 ${esc(f[side].raw)}</small><small>解释状态：${esc({known:'已有解释',unverified:'含义待核验',unknown:'数值未知'}[f[side].status]||f[side].status)}</small>${draft.id&&['known','pending'].includes(f[side].status)?`<button class="text-link" data-review-experiment="${esc(draft.id)}" data-path="${esc(f.path)}" data-side="${side}">带此证据核实</button>`:''}</div>`).join('')}</article>`).join('')||'<p class="insight-empty">没有符合筛选的变化字段。</p>'}</div><div class="insight-pagination">${button('上一页变化字段','fields-previous',fieldPage===0)}<span>${fields.length} 项 · ${fieldPage+1} / ${pages}</span>${button('下一页变化字段','fields-next',fieldPage+1===pages)}</div>`;
      node.querySelector('#lab-chosen-count').textContent=`已选 ${chosen.size} / 40 项；筛选不会自动清除已选项`;
    }
    function paintRecords(){
      const el=node?.querySelector('#lab-records');if(!el||!data)return;
      const rows=data.records.filter(r=>r.deleted===(recordFilter==='deleted')),pages=Math.max(1,Math.ceil(rows.length/10));page=Math.min(page,pages-1);
      el.innerHTML=(rows.slice(page*10,page*10+10).map(r=>`<article class="rule-record" data-lab-record="${esc(r.id)}"><div class="insight-heading"><h4>${esc(r.body.title)}</h4><span class="insight-badge">研究记录 · ${r.body.change_count} 项字段</span></div><p>动作：${esc(r.body.action_text)}<br>动作时间 ${esc(time(r.body.action_at))}</p><div class="insight-actions">${button('回看实验','review',sampleLoading.before||sampleLoading.after,`data-id="${esc(r.id)}"`)}${r.deleted?button('恢复实验','restore',false,`data-id="${esc(r.id)}"`):button('删除实验','delete',false,`data-id="${esc(r.id)}"`)}</div></article>`).join('')||'<p class="insight-empty">没有符合筛选的实验记录</p>')+`<div class="insight-pagination">${button('上一页实验','previous',page===0)}<span>${page+1} / ${pages}</span>${button('下一页实验','next',page+1===pages)}</div>`;
    }
    async function loadRecords(){
      if(!owner)return false;const identity=owner,token=++serial;attempted=true;loading=true;error='';paint();
      try{const result=await request('/api/insights/experiments');if(!valid(token,serial,identity))return false;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');data=result;return true;
      }catch(failure){if(valid(token,serial,identity))error=failure.message;return false;}
      finally{if(valid(token,serial,identity)){loading=false;paint();}}
    }
    async function loadSamples(side,more=false){
      if(!owner||draft.id||busy||!dates[side])return;
      const identity=owner,token=++sampleSerial[side],date=more?lists[side].date:dates[side],cursor=more?lists[side].next_cursor:null;
      sampleLoading[side]=true;sampleError[side]='';paint();
      try{const result=await request('/api/insights/timeline?date='+encodeURIComponent(date)+(cursor?'&cursor='+encodeURIComponent(cursor):''));
        if(!valid(token,sampleSerial[side],identity))return;if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        if(more)result.items=lists[side].items.concat(result.items);lists[side]=result;
        if(!result.items.some(r=>r.key===selected[side])){selected[side]=result.items[side==='after'&&result.items.length>1?1:0]?.key||'';comparison=null;detailSerial++;}
      }catch(failure){if(valid(token,sampleSerial[side],identity))sampleError[side]=failure.message;}
      finally{if(valid(token,sampleSerial[side],identity)){sampleLoading[side]=false;paint();}}
    }
    async function readDetail(identityToRead,preferredPath=''){
      if(busy||sampleLoading.before||sampleLoading.after)return;
      const identity=owner,token=++detailSerial;busy=true;error='';paint();
      try{
        const result=await request(identityToRead?'/api/insights/experiments/detail?id='+encodeURIComponent(identityToRead):'/api/insights/compare?before='+encodeURIComponent(selected.before)+'&after='+encodeURIComponent(selected.after));
        if(!valid(token,detailSerial,identity))return;if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        if(identityToRead){const b=result.body;draft={id:result.id,title:b.title,action_text:b.action_text,action_time:beijingInput(b.action_at),note:b.note};comparison={before:b.before,after:b.after,changes:b.changes};chosen=new Set(b.paths);}
        else{comparison=result;chosen=new Set(result.changes.slice(0,40).map(f=>f.path));}
        if(identityToRead||preferredPath)dirty=false;
        if(preferredPath){chosen=new Set(result.changes.filter(f=>f.path===preferredPath).map(f=>f.path));query=preferredPath;}
        else query='';fieldPage=0;
      }catch(failure){if(valid(token,detailSerial,identity))error=failure.message;}
      finally{if(valid(token,detailSerial,identity)){busy=false;paint();}}
    }
    async function mutate(action,id){
      if(!data||busy||loading)return;
      if(action==='save'&&(!comparison||!node.querySelector('#lab-form').reportValidity()))return;
      const identity=owner,token=++writeSerial,payload={action,id,revision:data.revision,context:owner};
      if(action==='save')Object.assign(payload,{id:draft.id,title:draft.title,action_text:draft.action_text,action_at:actionAt(),note:draft.note,before:comparison.before.key,after:comparison.after.key,paths:[...chosen]});
      busy=true;error='';status='';paint();
      try{const result=await request('/api/insights/experiments',payload);if(!valid(token,writeSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');data.revision=result.revision;data.can_undo=result.can_undo;
        status=action==='save'?'实验记录已保存。':'实验操作已保存。';
        if(action==='save'||action==='delete'&&draft.id===id){draft=blank();dirty=false;comparison=null;chosen.clear();}
        if(!await loadRecords()&&valid(token,writeSerial,identity))status+=' 列表尚未刷新，请重新读取核对。';
      }catch(failure){if(valid(token,writeSerial,identity))error=failure.message+' 填写内容保留；请重新读取核对后操作。';}
      finally{if(valid(token,writeSerial,identity)){busy=false;paint();}}
    }
    function mount(container){
      const changed=owner!==context(),remount=node!==container;node=container;
      if(changed){owner=context();data=null;draft=blank();dirty=false;comparison=null;chosen.clear();attempted=loading=busy=false;serial++;detailSerial++;writeSerial++;error=status='';for(const side of ['before','after']){lists[side]=null;selected[side]='';sampleLoading[side]=false;sampleSerial[side]++;sampleError[side]='';}}
      if(changed||remount)paint();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;const el=event.target;
      if(event.type==='input'){
        const mapping={'lab-title':'title','lab-action-text':'action_text','lab-action-time':'action_time','lab-note':'note'};
        if(mapping[el.id]){draft[mapping[el.id]]=el.value;dirty=true;paintWarnings();return true;}
        if(el.id.startsWith('lab-date-')){const side=el.id.endsWith('before')?'before':'after';if(dates[side]===el.value)return true;dates[side]=el.value;lists[side]=null;selected[side]='';sampleSerial[side]++;sampleLoading[side]=false;sampleError[side]='';comparison=null;chosen.clear();detailSerial++;busy=false;paint();return true;}
        if(el.id==='lab-search'){query=el.value;fieldPage=0;paintChanges();return true;}
      }
      if(event.type==='change'){
        if(el.id.startsWith('lab-sample-')){selected[el.id.endsWith('before')?'before':'after']=el.value;comparison=null;detailSerial++;paint();return true;}
        if(el.dataset.labPath&&!draft.id){if(el.checked&&chosen.size>=40){el.checked=false;status='最多选择 40 项。';}else if(el.checked)chosen.add(el.dataset.labPath);else chosen.delete(el.dataset.labPath);paintChanges();return true;}
        if(el.id==='lab-record-filter'){recordFilter=el.value;page=0;paintRecords();return true;}
      }
      if(event.type!=='click')return false;const target=el.closest('[data-lab]');if(!target||target.disabled)return false;
      const action=target.dataset.lab;
      if(action==='load')loadRecords();else if(action==='new'){draft=blank();dirty=false;comparison=null;chosen.clear();error=status='';detailSerial++;paint();}
      else if(action==='samples'||action==='more')loadSamples(target.dataset.side,action==='more');
      else if(action==='compare')readDetail();else if(action==='review')readDetail(target.dataset.id);
      else if(action==='select-filter'){chosen=new Set(filtered().slice(0,40).map(f=>f.path));paintChanges();}
      else if(action==='clear-fields'){chosen.clear();paintChanges();}
      else if(action==='fields-previous'){fieldPage--;paintChanges();}else if(action==='fields-next'){fieldPage++;paintChanges();}
      else if(action==='previous'){page--;paintRecords();}else if(action==='next'){page++;paintRecords();}
      else mutate(action,target.dataset.id);return true;
    }
    function openEvidence(selection){
      if(dirty){error='实验室有未保存内容，请先保存，或点新建实验放弃当前内容后再带入样本。';paint();return;}
      if(selection.id){readDetail(selection.id);return;}
      if(busy)return;
      draft=blank();draft.title=selection.name+'观察';
      draft.action_time='';
      comparison=null;chosen.clear();
      for(const side of ['before','after']){
        const point=selection[side];selected[side]=point.key;dates[side]=beijingInput(point.observed_at).slice(0,10);
        lists[side]={date:dates[side],items:[point],next_cursor:null};
      }
      paint();readDetail(undefined,selection.path);
    }
    return {mount,handle,openEvidence};
  }
  root.ParameterExperimentsPage={create};
})(window);
