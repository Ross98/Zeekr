(function(root){
  'use strict';
  const dateAt=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const money=value=>(value/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
  const number=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1}).format(value):'未知';
  const statuses={due:'已到期',upcoming:'尚未到期',unknown:'里程待确认',completed:'已完成'};
  const blankExpense=date=>({id:'',date,category:'保险',title:'',amount:'',odometer:'',note:'',revision:null});
  const blankReminder=()=>({id:'',title:'',due_date:'',due_km:'',note:'',revision:null});
  function selectExpenses(book,{state='active',category='',query=''}={}){
    const term=query.trim().toLowerCase();
    return (state==='deleted'?book.trash:book.entries).filter(row=>
      (!category||row.category===category)&&(!term||[row.title,row.category,row.date,row.note].join(' ').toLowerCase().includes(term)))
      .sort((a,b)=>b.date.localeCompare(a.date)||(b.updated_at||0)-(a.updated_at||0)||b.id.localeCompare(a.id));
  }
  function groupExpenses(rows){
    const groups=new Map();
    for(const row of rows){const month=row.date.slice(0,7);if(!groups.has(month))groups.set(month,{month,count:0,cents:0,rows:[]});const group=groups.get(month);group.count++;group.cents+=row.amount_cents;group.rows.push(row);}
    return [...groups.values()];
  }
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',mode='expenses',startDate=dateAt(Date.now()).slice(0,7)+'-01',endDate=dateAt(Date.now()),data=null;
    let loading=false,busy=false,serial=0,writeSerial=0,error='',status='';
    let drafts={expenses:blankExpense(dateAt(Date.now())),reminders:blankReminder()};
    let expenseState='active',expenseCategory='',historyQuery='',reminderFilter='all',page=0;
    let editorOpen={expenses:false,reminders:false};
    let attempted=false,lastLoaded=0,dirty={expenses:false,reminders:false},pendingAction=null;
    const persist=()=>root.BookSession?.write(owner,'life',{mode,startDate,endDate,drafts,dirty,expenseState,expenseCategory,historyQuery,reminderFilter,page,attempted,editorOpen});
    function protect(action){if(dirty[mode]){pendingAction=action;paint();return true;}return false;}
    const context=()=>getState()?.insights_context||'';
    const valid=(token,current,identity)=>token===current&&owner===identity&&context()===identity;
    const button=(label,action,disabled=false,extra='')=>`<button class="button secondary" data-life="${action}" ${disabled||busy?'disabled':''} ${extra}>${label}</button>`;
    const defaultDate=()=>dateAt(Date.now());
    const resetDraft=collection=>{dirty[collection]=false;drafts[collection]=collection==='expenses'?blankExpense(defaultDate()):blankReminder();};
    const draft=()=>drafts[mode];
    function field(label,name,type='text',extra=''){
      return `<label>${label}<input id="life-${name}" data-life-field="${name}" type="${type}" value="${esc(draft()[name])}" ${busy?'disabled':''} ${extra}></label>`;
    }
    function note(label){return `<label class="ledger-wide">${label}<textarea id="life-note" aria-label="${label}" data-life-field="note" maxlength="1000" rows="3" ${busy?'disabled':''}>${esc(draft().note)}</textarea></label>`;}
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected||!active())return;
      persist();
      const focused=node.contains(document.activeElement)?document.activeElement:null;
      const focus=focused?{id:focused.id,start:focused.selectionStart,end:focused.selectionEnd}:null;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">车辆生活账本</span><h2>日常支出，下次要做的事</h2>${root.booksCanReturn?.()?'<button class="button secondary" data-books-return>返回来源页面</button>':''}<p>费用按实记，保养与到期事项留个提醒。</p></div><span class="insight-source">本机保存 · 站内待办</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>开始日期<input id="life-start" type="date" value="${esc(startDate)}" ${busy?'disabled':''}></label><label>结束日期<input id="life-end" type="date" value="${esc(endDate)}" ${busy?'disabled':''}></label>${button('查询生活账本','load',!owner||!startDate||!endDate||loading)}</div>${mode==='expenses'?`<div class="insight-actions life-history-ranges">${button('本月','range-month',loading)}${button('今年','range-year',loading)}${button('全部历史','range-all',loading||!data?.expense_range?.start_date)}</div>`:''}${loading?'<p role="status">正在读取记录…</p>':''}${status?`<p role="status" class="insight-note">${esc(status)}</p>`:''}${error?`<p role="alert" class="notice error">${esc(error)}</p>`:''}${!owner?'<p>等待当前账号的车辆缓存后，可管理账本。</p>':''}<div class="insight-actions">${['expenses','reminders'].map(key=>`<button class="button secondary" data-life-mode="${key}" aria-pressed="${mode===key}" ${busy?'disabled':''}>${key==='expenses'?'日常支出':'保养与到期待办'}</button>`).join('')}</div><p class="insight-note">选择日期后点击查询，支出按填写日期归入区间，不摊销保险或保养成本；充电账本费用另计，避免重复录入。待办不限区间，仅在本站显示，不发送外部通知。</p></section>
        ${pendingAction?`<div class="notice info" role="status"><p>当前有未保存草稿。放弃后才能继续此操作。</p>${button('继续编辑草稿','keep')}${button('放弃草稿，继续','discard')}</div>`:''}
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
        ${editorOpen[mode]?`<section class="card insight-panel"><div class="insight-heading"><h3>${draft().id?'编辑支出':'新增支出'}</h3>${button('取消编辑','cancel')}</div><form id="life-form" class="ledger-form" novalidate>${field('支出日期','date','date','required')}${field('支出分类','category','text','required maxlength="24" list="life-categories"')}<datalist id="life-categories">${data.category_choices.map(c=>`<option value="${esc(c)}"></option>`).join('')}</datalist>${field('支出名称','title','text','required maxlength="80"')}${field('实际支出金额（元）','amount','number','required min="0" max="10000000" step=".01"')}${field('支出时里程（km，可选）','odometer','number','min="0" max="10000000" step=".1"')}${note('支出备注')}</form><p class="insight-note">可输入自己的分类（24 字以内）。金额为包含各项费用的最终总额，免费项目填 0；里程留空时保持未知。</p>${conflict()}<div class="insight-actions">${button('保存支出','save',loading||!owner)}</div></section>`:''}
        <section class="card insight-panel"><div class="insight-heading"><h3>历史支出记录</h3>${button('新增支出','new')}<div class="insight-toolbar life-history-filters"><label class="life-history-search">搜索历史记录<input id="life-history-search" type="search" aria-label="搜索历史记录" placeholder="名称 / 分类 / 日期 / 备注" value="${esc(historyQuery)}"></label><label>支出记录状态<select id="life-expense-state" aria-label="支出记录状态"><option value="active" ${expenseState==='active'?'selected':''}>保留的记录</option><option value="deleted" ${expenseState==='deleted'?'selected':''}>已删除记录</option></select></label><label>分类筛选<select id="life-category-filter" aria-label="分类筛选"><option value="">全部分类</option>${data.category_choices.map(c=>`<option value="${esc(c)}" ${expenseCategory===c?'selected':''}>${esc(c)}</option>`).join('')}</select></label></div></div><div id="life-rows"></div></section>`;
    }
    function reminderView(){
      const tasks=data.reminders,km=data.odometer;
      return `<section class="card insight-panel"><div class="insight-heading"><h3>保养与到期待办</h3>${button('撤销待办操作','undo',!tasks.can_undo)}</div><div class="insight-metrics">${Object.entries(statuses).map(([key,label])=>`<div><span>${label}</span><strong>${tasks.counts[key]}</strong></div>`).join('')}</div><p class="insight-note">当前可用里程：${number(km.value)} km · ${km.reason==='fresh'?'有效缓存观测':'缺少有效且新鲜的里程观测'}<br>车辆时间 ${esc(time(km.state_time))} · 读取时间 ${esc(time(km.fetched_at))}<br>本次检查 ${esc(time(data.as_of))}。页面打开时定期更新；旧缓存不用于里程到期判断。</p></section>
        ${editorOpen[mode]?`<section class="card insight-panel"><div class="insight-heading"><h3>${draft().id?'编辑待办':'新增待办'}</h3>${button('取消编辑','cancel')}</div><form id="life-form" class="ledger-form" novalidate>${field('待办名称','title','text','required maxlength="80"')}${field('到期日期','due_date','date')}${field('到期里程（km）','due_km','number','min="0" max="10000000" step=".1"')}${note('待办备注')}</form><p class="insight-note">至少填写日期或里程之一；两项都填时，任一达到就标到期。里程未知时保持待确认，不把未知当作未到期。完成事项由你手动标记；编辑说明不会重新开启已完成事项。</p>${conflict()}<div class="insight-actions">${button('保存待办','save',loading||!owner)}</div></section>`:''}
        <section class="card insight-panel"><div class="insight-heading"><h3>全部待办</h3>${button('新增待办','new')}<label>待办筛选<select id="life-reminder-filter" aria-label="待办筛选">${Object.entries({all:'未完成（全部）',due:'已到期',upcoming:'尚未到期',unknown:'里程待确认',completed:'已完成',deleted:'已删除'}).map(([key,label])=>`<option value="${key}" ${reminderFilter===key?'selected':''}>${label}</option>`).join('')}</select></label></div><p class="insight-note">最多 200 条，含可恢复记录。完成、重新开启、删除和恢复都可撤销上一步。</p><div id="life-rows"></div></section>`;
    }
    function rows(){
      if(mode==='expenses')return selectExpenses(data.expenses,{state:expenseState,category:expenseCategory,query:historyQuery});
      const order={due:0,unknown:1,upcoming:2,completed:3};
      return data.reminders.records.filter(r=>reminderFilter==='deleted'?r.deleted:!r.deleted&&(reminderFilter==='all'?r.status!=='completed':r.status===reminderFilter)).sort((a,b)=>order[a.status]-order[b.status]||(a.due_date||'9999').localeCompare(b.due_date||'9999')||b.updated_at-a.updated_at);
    }
    function paintRows(){
      const el=node?.querySelector('#life-rows');if(!data||!el)return;
      const list=rows(),pages=Math.max(1,Math.ceil(list.length/10));page=Math.min(page,pages-1);
      if(mode==='expenses'){
        const fullGroups=new Map(groupExpenses(list).map(group=>[group.month,group]));
        const selectedGroups=groupExpenses(list.slice(page*10,page*10+10));
        const total=list.reduce((sum,row)=>sum+row.amount_cents,0);
        el.innerHTML=`<p class="insight-note life-history-summary" role="status">匹配 ${list.length} 笔 · ${expenseState==='deleted'?'已删除合计（不计费用）':'筛选合计'} ${money(total)} 元 · 日期从新到旧</p>`+
          selectedGroups.map(group=>{const full=fullGroups.get(group.month);return `<section class="life-history-month" aria-label="${esc(group.month)}支出"><div class="life-history-month-heading"><h4>${esc(group.month.replace('-','年'))}月</h4><span>该月匹配 ${full.count} 笔 · ${money(full.cents)} 元</span></div><div class="life-history-column-head" aria-hidden="true"><span>日期</span><span>项目与分类</span><span>实际金额</span><span>操作</span></div>${group.rows.map(row=>{
            const extra=`data-id="${esc(row.id)}"`;
            return `<article class="life-history-row" data-life-expense="${esc(row.id)}"><div class="life-history-row-main"><time datetime="${esc(row.date)}">${esc(row.date)}</time><div class="life-history-item"><strong>${esc(row.title)}</strong><span>${esc(row.category)}</span></div><strong class="life-history-amount">${money(row.amount_cents)} 元</strong><div class="life-history-actions">${row.deleted?button('恢复支出','restore',false,extra):button('编辑支出','edit',false,extra)+button('删除支出','delete',false,extra)}</div></div>${row.note||row.odometer!==null?`<details class="life-history-details" data-detail="life-expense-${esc(row.id)}"><summary>备注与里程</summary>${row.note?`<p class="ledger-note">${esc(row.note)}</p>`:''}<p>手工记录里程 ${number(row.odometer)} km</p></details>`:''}</article>`;
          }).join('')}</section>`;}).join('')+(!list.length?'<p class="insight-empty">没有符合筛选的历史记录。可清空搜索或切换日期区间。</p>':'')+
          `<div class="insight-pagination">${button('上一页生活记录','previous',page===0)}<span>第 ${page+1} / ${pages} 页 · ${list.length? page*10+1:0}–${Math.min((page+1)*10,list.length)} 笔</span>${button('下一页生活记录','next',page+1===pages)}</div>`;
        return;
      }
      el.innerHTML=(list.slice(page*10,page*10+10).map(row=>{
        const extra=`data-id="${esc(row.id)}"`,expense=mode==='expenses';
        return `<article class="rule-record" ${expense?'data-life-expense':'data-life-reminder'}="${esc(row.id)}"><div class="insight-heading"><h4>${esc(row.title)}</h4><span class="insight-badge">${expense?esc(row.category):statuses[row.status]}</span></div>${expense?`<p>${row.date} · 实际 ${money(row.amount_cents)} 元<br>手工记录里程 ${number(row.odometer)} km</p>`:`<p>日期 ${row.due_date||'未设置'} · 里程 ${number(row.due_km)} km</p>${row.status==='due'?`<p>到期依据：${row.due_reasons.map(r=>r==='date'?'日期已到':'有效里程已达').join('、')}</p>`:''}${row.completed_at!==null?`<p>已完成 · ${esc(time(row.completed_at))}</p>`:''}`}${row.note?`<p class="ledger-note">${esc(row.note)}</p>`:''}<div class="insight-actions">${row.deleted?button(expense?'恢复支出':'恢复待办','restore',false,extra):button(expense?'编辑支出':'编辑待办','edit',false,extra)+(expense?'':button(row.status==='completed'?'重新开启':'标记完成',row.status==='completed'?'reopen':'complete',false,extra))+button(expense?'删除支出':'删除待办','delete',false,extra)}</div></article>`;
      }).join('')||'<p class="insight-empty">没有符合筛选的记录。</p>')+`<div class="insight-pagination">${button('上一页生活记录','previous',page===0)}<span>${page+1} / ${pages}</span>${button('下一页生活记录','next',page+1===pages)}</div>`;
    }
    async function load(){
      if(!owner||!startDate||!endDate)return false;
      if(endDate<startDate){error='结束日期不能早于开始日期。';paint();return false;}
      attempted=true;lastLoaded=Date.now();const identity=owner,token=++serial,selectedStart=startDate,selectedEnd=endDate;loading=true;error='';paint();
      try{const result=await request('/api/insights/life?start='+encodeURIComponent(selectedStart)+'&end='+encodeURIComponent(selectedEnd));
        if(!valid(token,serial,identity)||selectedStart!==startDate||selectedEnd!==endDate)return false;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=result;lastLoaded=Date.now();return true;
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
        status='生活账本操作已保存。';
        if(action==='save'&&collection==='expenses'&&(payload.date<startDate||payload.date>endDate)){
          startDate=payload.date.slice(0,7)+'-01';endDate=payload.date.slice(0,7)+'-'+new Date(Date.UTC(Number(payload.date.slice(0,4)),Number(payload.date.slice(5,7)),0)).getUTCDate();
          status+=' 已切换到支出所在月份。';
        }
        if(action==='save'){resetDraft(collection);editorOpen[collection]=false;}
        else if(action==='delete'&&drafts[collection].id===id)resetDraft(collection);
        data=null;
        if(!await load()&&valid(token,writeSerial,identity))status+=' 列表尚未刷新，请重新查询核对。';
      }catch(failure){if(valid(token,writeSerial,identity))error=failure.message+' 填写内容保留。';}
      finally{if(valid(token,writeSerial,identity)){busy=false;paint();}}
    }
    function edit(id,force=false){
      if(!force&&protect(()=>edit(id,true)))return;
      const row=rows().find(r=>r.id===id);if(!row)return;
      drafts[mode]=mode==='expenses'?{id:row.id,date:row.date,category:row.category,title:row.title,amount:(row.amount_cents/100).toFixed(2),odometer:row.odometer??'',note:row.note,revision:data[mode].revision}:{id:row.id,title:row.title,due_date:row.due_date||'',due_km:row.due_km??'',note:row.note,revision:data[mode].revision};
      dirty[mode]=false;editorOpen[mode]=true;error=status='';paint();node.querySelector('#life-form').scrollIntoView({block:'start'});
    }
    function mount(container){
      const changed=owner!==context(),remount=node!==container;node=container;
      if(changed){owner=context();data=null;mode='expenses';loading=busy=false;serial++;writeSerial++;error=status='';resetDraft('expenses');resetDraft('reminders');expenseState='active';expenseCategory='';historyQuery='';reminderFilter='all';page=0;}
      if(changed){
        attempted=true;lastLoaded=0;pendingAction=null;
        const saved=root.BookSession?.read(owner,'life');
        if(saved){mode=saved.mode==='reminders'?'reminders':'expenses';startDate=saved.startDate||startDate;endDate=saved.endDate||endDate;drafts={expenses:{...blankExpense(defaultDate()),...saved.drafts?.expenses},reminders:{...blankReminder(),...saved.drafts?.reminders}};dirty={expenses:!!saved.dirty?.expenses,reminders:!!saved.dirty?.reminders};expenseState=saved.expenseState||'active';expenseCategory=saved.expenseCategory||'';historyQuery=typeof saved.historyQuery==='string'?saved.historyQuery:'';reminderFilter=saved.reminderFilter||'all';page=saved.page||0;attempted=true;editorOpen={expenses:!!saved.editorOpen?.expenses||dirty.expenses,reminders:!!saved.editorOpen?.reminders||dirty.reminders};}
      }
      if(changed||remount)paint();
      if(attempted&&!loading&&!busy&&active()&&(changed||Date.now()-lastLoaded>=30000))load();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;const el=event.target;
      if(event.type==='input'){
        if(el.id==='life-history-search'){historyQuery=el.value;page=0;paintRows();persist();return true;}
        if(el.id==='life-start'||el.id==='life-end'){
          if(el.id==='life-start')startDate=el.value;else endDate=el.value;
          serial++;loading=false;error='';data=null;page=0;paint();return true;
        }
        if(el.dataset.lifeField){if(draft().revision===null&&data)draft().revision=data[mode].revision;draft()[el.dataset.lifeField]=el.value;dirty[mode]=true;persist();return true;}
      }
      if(event.type==='change'){
        if(el.id==='life-expense-state')expenseState=el.value;else if(el.id==='life-category-filter')expenseCategory=el.value;
        else if(el.id==='life-reminder-filter')reminderFilter=el.value;else return false;
        page=0;paintRows();persist();return true;
      }
      if(event.type!=='click')return false;
      const sub=el.closest('[data-life-mode]');if(sub&&!sub.disabled){mode=sub.dataset.lifeMode;page=0;paint();return true;}
      const target=el.closest('[data-life]');if(!target||target.disabled)return false;const action=target.dataset.life;
      if(action.startsWith('range-')){
        const today=defaultDate();
        if(action==='range-all'){if(!data?.expense_range?.start_date)return true;startDate=data.expense_range.start_date;endDate=data.expense_range.end_date;}
        else{startDate=action==='range-year'?today.slice(0,4)+'-01-01':today.slice(0,7)+'-01';endDate=today;}
        serial++;loading=false;data=null;page=0;load();return true;
      }
      if(['new','cancel'].includes(action)&&protect(()=>{dirty[mode]=false;const next=node.querySelector(`[data-life="${action}"]`);if(next)handle({type:'click',target:next});}))return true;
      if(action==='keep'){pendingAction=null;paint();}
      else if(action==='discard'){const follow=pendingAction;pendingAction=null;dirty[mode]=false;follow?.();}
      else if(action==='load')load();else if(action==='cancel'){resetDraft(mode);editorOpen[mode]=false;paint();}
      else if(action==='new'){editorOpen[mode]=true;resetDraft(mode);error=status='';paint();}
      else if(action==='edit')edit(target.dataset.id);else if(action==='adopt'){draft().revision=data[mode].revision;error='';paint();}
      else if(action==='previous'){page--;paintRows();}else if(action==='next'){page++;paintRows();}
      else mutate(action,target.dataset.id);persist();return true;
    }
    async function openDate(date){
      startDate=date.slice(0,7)+'-01';endDate=date.slice(0,7)+'-'+new Date(Date.UTC(Number(date.slice(0,4)),Number(date.slice(5,7)),0)).getUTCDate();
      serial++;loading=false;data=null;page=0;await load();
    }
    return {mount,handle,openDate};
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={selectExpenses,groupExpenses};
  else root.VehicleLifePage={create};
})(typeof window==='undefined'?globalThis:window);
