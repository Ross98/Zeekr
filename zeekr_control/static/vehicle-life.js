(function(root){
  'use strict';
  const dateAt=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const money=value=>(value/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
  const number=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1}).format(value):'未知';
  const statuses={due:'已到期',upcoming:'尚未到期',unknown:'里程待确认',completed:'已完成'};
  const blankExpense=date=>({id:'',date,category:'保险',title:'',amount:'',odometer:'',note:'',revision:null});
  const blankReminder=()=>({id:'',title:'',due_date:'',due_km:'',note:'',revision:null});
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',mode='expenses',startDate=dateAt(Date.now()).slice(0,7)+'-01',endDate=dateAt(Date.now()),data=null;
    let loading=false,busy=false,serial=0,writeSerial=0,error='',status='';
    let drafts={expenses:blankExpense(dateAt(Date.now())),reminders:blankReminder()};
    let expenseState='active',expenseCategory='',reminderFilter='all',page=0;
    const context=()=>getState()?.insights_context||'';
    const valid=(token,current,identity)=>token===current&&owner===identity&&context()===identity;
    const button=(label,action,disabled=false,extra='')=>`<button class="button secondary" data-life="${action}" ${disabled||busy?'disabled':''} ${extra}>${label}</button>`;
    const defaultDate=()=>dateAt(Date.now());
    const resetDraft=collection=>{drafts[collection]=collection==='expenses'?blankExpense(defaultDate()):blankReminder();};
    const draft=()=>drafts[mode];
    function field(label,name,type='text',extra=''){
      return `<label>${label}<input id="life-${name}" data-life-field="${name}" type="${type}" value="${esc(draft()[name])}" ${busy?'disabled':''} ${extra}></label>`;
    }
    function note(label){return `<label class="ledger-wide">${label}<textarea id="life-note" aria-label="${label}" data-life-field="note" maxlength="1000" rows="3" ${busy?'disabled':''}>${esc(draft().note)}</textarea></label>`;}
    function paint(){
      if(!node?.isConnected||!active())return;
      const focused=node.contains(document.activeElement)?document.activeElement:null;
      const focus=focused?{id:focused.id,start:focused.selectionStart,end:focused.selectionEnd}:null;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">车辆生活账本</span><h2>日常支出，下次要做的事</h2><p>费用按实记，保养与到期事项留个提醒。</p></div><span class="insight-source">本机保存 · 站内待办</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>开始日期<input id="life-start" type="date" value="${esc(startDate)}" ${busy?'disabled':''}></label><label>结束日期<input id="life-end" type="date" value="${esc(endDate)}" ${busy?'disabled':''}></label>${button('查询生活账本','load',!owner||!startDate||!endDate||loading)}</div>${loading?'<p role="status">正在读取记录…</p>':''}${status?`<p role="status" class="insight-note">${esc(status)}</p>`:''}${error?`<p role="alert" class="notice error">${esc(error)}</p>`:''}${!owner?'<p>等待当前账号的车辆缓存后，可管理账本。</p>':''}<div class="insight-actions">${['expenses','reminders'].map(key=>`<button class="button secondary" data-life-mode="${key}" aria-pressed="${mode===key}" ${busy?'disabled':''}>${key==='expenses'?'日常支出':'保养与到期待办'}</button>`).join('')}</div><p class="insight-note">选择日期后点击查询，支出按填写日期归入区间，不摊销保险或保养成本；充电账本费用另计，避免重复录入。待办不限区间，仅在本站显示，不发送外部通知。</p></section>
        ${data?mode==='expenses'?expenseView():reminderView():''}`;
      paintRows();
      if(focus){const el=document.getElementById(focus.id);if(el&&!el.disabled){el.focus({preventScroll:true});if(focus.start!==null)el.setSelectionRange?.(focus.start,focus.end);}}
    }
    function conflict(){
      return draft().revision!==null&&draft().revision!==data[mode].revision?`<p class="insight-note insight-warning">记录已有更新，填写内容保留。先核对下方列表，再决定是否继续使用这份草稿。</p>${button('已核对列表，继续编辑','adopt')}`:'';
    }
    function expenseView(){
      const book=data.expenses;
      return `<section class="card insight-panel"><div class="insight-heading"><h3>${esc(data.window.start_date)} 至 ${esc(data.window.end_date)} · 已录支出</h3>${button('撤销支出操作','undo',!book.can_undo)}</div><div class="insight-metrics"><div id="life-total"><span>区间已录支出</span><strong>${money(book.total_cents)} 元</strong><small>${book.entries.length} 笔；无记录不等于实际零成本</small></div>${Object.entries(book.categories).map(([name,row])=>`<div><span>${esc(name)} · ${row.count} 笔</span><strong>${money(row.amount_cents)} 元</strong></div>`).join('')}</div></section>
        <section class="card insight-panel"><div class="insight-heading"><h3>${draft().id?'编辑支出':'新增支出'}</h3>${button('新增支出','new')}</div><form id="life-form" class="ledger-form" novalidate>${field('支出日期','date','date','required')}${field('支出分类','category','text','required maxlength="24" list="life-categories"')}<datalist id="life-categories">${data.category_choices.map(c=>`<option value="${esc(c)}"></option>`).join('')}</datalist>${field('支出名称','title','text','required maxlength="80"')}${field('实际支出金额（元）','amount','number','required min="0" max="10000000" step=".01"')}${field('支出时里程（km，可选）','odometer','number','min="0" max="10000000" step=".1"')}${note('支出备注')}</form><p class="insight-note">可输入自己的分类（24 字以内）。金额为包含各项费用的最终总额，免费项目填 0；里程留空时保持未知。</p>${conflict()}<div class="insight-actions">${button('保存支出','save',loading||!owner)}</div></section>
        <section class="card insight-panel"><div class="insight-heading"><h3>支出记录</h3><div class="insight-toolbar"><label>支出记录状态<select id="life-expense-state" aria-label="支出记录状态"><option value="active" ${expenseState==='active'?'selected':''}>保留的记录</option><option value="deleted" ${expenseState==='deleted'?'selected':''}>已删除记录</option></select></label><label>分类筛选<select id="life-category-filter" aria-label="分类筛选"><option value="">全部分类</option>${data.category_choices.map(c=>`<option value="${esc(c)}" ${expenseCategory===c?'selected':''}>${esc(c)}</option>`).join('')}</select></label></div></div><div id="life-rows"></div></section>`;
    }
    function reminderView(){
      const tasks=data.reminders,km=data.odometer;
      return `<section class="card insight-panel"><div class="insight-heading"><h3>保养与到期待办</h3>${button('撤销待办操作','undo',!tasks.can_undo)}</div><div class="insight-metrics">${Object.entries(statuses).map(([key,label])=>`<div><span>${label}</span><strong>${tasks.counts[key]}</strong></div>`).join('')}</div><p class="insight-note">当前可用里程：${number(km.value)} km · ${km.reason==='fresh'?'有效缓存观测':'缺少有效且新鲜的里程观测'}<br>车辆时间 ${esc(time(km.state_time))} · 读取时间 ${esc(time(km.fetched_at))}<br>本次检查 ${esc(time(data.as_of))}。页面打开时定期更新；旧缓存不用于里程到期判断。</p></section>
        <section class="card insight-panel"><div class="insight-heading"><h3>${draft().id?'编辑待办':'新增待办'}</h3>${button('新增待办','new')}</div><form id="life-form" class="ledger-form" novalidate>${field('待办名称','title','text','required maxlength="80"')}${field('到期日期','due_date','date')}${field('到期里程（km）','due_km','number','min="0" max="10000000" step=".1"')}${note('待办备注')}</form><p class="insight-note">至少填写日期或里程之一；两项都填时，任一达到就标到期。里程未知时保持待确认，不把未知当作未到期。完成事项由你手动标记；编辑说明不会重新开启已完成事项。</p>${conflict()}<div class="insight-actions">${button('保存待办','save',loading||!owner)}</div></section>
        <section class="card insight-panel"><div class="insight-heading"><h3>全部待办</h3><label>待办筛选<select id="life-reminder-filter" aria-label="待办筛选">${Object.entries({all:'未完成（全部）',due:'已到期',upcoming:'尚未到期',unknown:'里程待确认',completed:'已完成',deleted:'已删除'}).map(([key,label])=>`<option value="${key}" ${reminderFilter===key?'selected':''}>${label}</option>`).join('')}</select></label></div><p class="insight-note">最多 200 条，含可恢复记录。完成、重新开启、删除和恢复都可撤销上一步。</p><div id="life-rows"></div></section>`;
    }
    function rows(){
      if(mode==='expenses')return (expenseState==='deleted'?data.expenses.trash:data.expenses.entries).filter(r=>!expenseCategory||r.category===expenseCategory);
      const order={due:0,unknown:1,upcoming:2,completed:3};
      return data.reminders.records.filter(r=>reminderFilter==='deleted'?r.deleted:!r.deleted&&(reminderFilter==='all'?r.status!=='completed':r.status===reminderFilter)).sort((a,b)=>order[a.status]-order[b.status]||(a.due_date||'9999').localeCompare(b.due_date||'9999')||b.updated_at-a.updated_at);
    }
    function paintRows(){
      const el=node?.querySelector('#life-rows');if(!data||!el)return;
      const list=rows(),pages=Math.max(1,Math.ceil(list.length/10));page=Math.min(page,pages-1);
      el.innerHTML=(list.slice(page*10,page*10+10).map(row=>{
        const extra=`data-id="${esc(row.id)}"`,expense=mode==='expenses';
        return `<article class="rule-record" ${expense?'data-life-expense':'data-life-reminder'}="${esc(row.id)}"><div class="insight-heading"><h4>${esc(row.title)}</h4><span class="insight-badge">${expense?esc(row.category):statuses[row.status]}</span></div>${expense?`<p>${row.date} · 实际 ${money(row.amount_cents)} 元<br>手工记录里程 ${number(row.odometer)} km</p>`:`<p>日期 ${row.due_date||'未设置'} · 里程 ${number(row.due_km)} km</p>${row.status==='due'?`<p>到期依据：${row.due_reasons.map(r=>r==='date'?'日期已到':'有效里程已达').join('、')}</p>`:''}${row.completed_at!==null?`<p>已完成 · ${esc(time(row.completed_at))}</p>`:''}`}${row.note?`<p class="ledger-note">${esc(row.note)}</p>`:''}<div class="insight-actions">${row.deleted?button(expense?'恢复支出':'恢复待办','restore',false,extra):button(expense?'编辑支出':'编辑待办','edit',false,extra)+(expense?'':button(row.status==='completed'?'重新开启':'标记完成',row.status==='completed'?'reopen':'complete',false,extra))+button(expense?'删除支出':'删除待办','delete',false,extra)}</div></article>`;
      }).join('')||'<p class="insight-empty">没有符合筛选的记录。</p>')+`<div class="insight-pagination">${button('上一页生活记录','previous',page===0)}<span>${page+1} / ${pages}</span>${button('下一页生活记录','next',page+1===pages)}</div>`;
    }
    async function load(){
      if(!owner||!startDate||!endDate)return false;
      if(endDate<startDate){error='结束日期不能早于开始日期。';paint();return false;}
      const identity=owner,token=++serial,selectedStart=startDate,selectedEnd=endDate;loading=true;error='';paint();
      try{const result=await request('/api/insights/life?start='+encodeURIComponent(selectedStart)+'&end='+encodeURIComponent(selectedEnd));
        if(!valid(token,serial,identity)||selectedStart!==startDate||selectedEnd!==endDate)return false;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=result;return true;
      }catch(failure){if(valid(token,serial,identity)&&selectedStart===startDate&&selectedEnd===endDate)error=failure.message;return false;}
      finally{if(valid(token,serial,identity)){loading=false;paint();}}
    }
    async function mutate(action,id){
      if(!data||busy||loading)return;
      if(action==='save'&&!node.querySelector('#life-form').reportValidity())return;
      const identity=owner,token=++writeSerial,collection=mode;
      const payload={...(action==='save'?draft():{}),collection,action,id:action==='save'?draft().id:id,
        revision:action==='save'?(draft().revision??data[collection].revision):data[collection].revision,context:owner};
      busy=true;error=status='';paint();
      try{const result=await request('/api/insights/life',payload);if(!valid(token,writeSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        status='生活账本操作已保存。点击查询更新列表。';
        if(action==='save')resetDraft(collection);
        else if(action==='delete'&&drafts[collection].id===id)resetDraft(collection);
        data=null;
      }catch(failure){if(valid(token,writeSerial,identity))error=failure.message+' 填写内容保留。';}
      finally{if(valid(token,writeSerial,identity)){busy=false;paint();}}
    }
    function edit(id){
      const row=rows().find(r=>r.id===id);if(!row)return;
      drafts[mode]=mode==='expenses'?{id:row.id,date:row.date,category:row.category,title:row.title,amount:(row.amount_cents/100).toFixed(2),odometer:row.odometer??'',note:row.note,revision:data[mode].revision}:{id:row.id,title:row.title,due_date:row.due_date||'',due_km:row.due_km??'',note:row.note,revision:data[mode].revision};
      error=status='';paint();node.querySelector('#life-form').scrollIntoView({block:'start'});
    }
    function mount(container){
      const changed=owner!==context(),remount=node!==container;node=container;
      if(changed){owner=context();data=null;mode='expenses';loading=busy=false;serial++;writeSerial++;error=status='';resetDraft('expenses');resetDraft('reminders');expenseState='active';expenseCategory='';reminderFilter='all';page=0;}
      if(changed||remount)paint();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;const el=event.target;
      if(event.type==='input'){
        if(el.id==='life-start'||el.id==='life-end'){
          if(el.id==='life-start')startDate=el.value;else endDate=el.value;
          error='';data=null;paint();return true;
        }
        if(el.dataset.lifeField){if(draft().revision===null&&data)draft().revision=data[mode].revision;draft()[el.dataset.lifeField]=el.value;return true;}
      }
      if(event.type==='change'){
        if(el.id==='life-expense-state')expenseState=el.value;else if(el.id==='life-category-filter')expenseCategory=el.value;
        else if(el.id==='life-reminder-filter')reminderFilter=el.value;else return false;
        page=0;paintRows();return true;
      }
      if(event.type!=='click')return false;
      const sub=el.closest('[data-life-mode]');if(sub&&!sub.disabled){mode=sub.dataset.lifeMode;page=0;paint();return true;}
      const target=el.closest('[data-life]');if(!target||target.disabled)return false;const action=target.dataset.life;
      if(action==='load')load();else if(action==='new'){resetDraft(mode);error=status='';paint();}
      else if(action==='edit')edit(target.dataset.id);else if(action==='adopt'){draft().revision=data[mode].revision;error='';paint();}
      else if(action==='previous'){page--;paintRows();}else if(action==='next'){page++;paintRows();}
      else mutate(action,target.dataset.id);return true;
    }
    return {mount,handle};
  }
  root.VehicleLifePage={create};
})(window);
