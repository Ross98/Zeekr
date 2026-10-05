(function(root) {
  'use strict';
  const changes = {first:'首条观测',new:'车辆时间推进',repeat:'重复缓存',revision:'同时间修订',regression:'车辆时间倒退',unknown:'时间未知'};
  const flags = {stale:'采集时已陈旧',unknown_time:'车辆时间未知',future_time:'车辆时间超前'};
  const time = value => Number.isFinite(value) ? new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(value)) : '未知';
  const today = () => new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const toolGroups = [
    {name:'数据分析',tools:[
      {id:'research',label:'数据利用',description:'全部字段、历史变化、场景分析与证据'},
      {id:'automatic',label:'自动洞察',description:'近期估算能耗与历史基线对照'}
    ]},
    {name:'历史回看',tools:[
      {id:'time',label:'车辆时间机',description:'历史归档、车况回看、前后参数变化'},
      {id:'review',label:'轻量用车回顾',description:'本周参考地点、实际费用与待补记录'}
    ]},
    {name:'参数核实',tools:[
      {id:'fields',label:'参数字典',description:'中文解释、原始字段与参数核实'},
      {id:'lab',label:'参数实验室',description:'保存实验、动作、样本与研究备注'}
    ]},
    {name:'能源与充电',page:'energy',tools:[
      {id:'charge-comparison',label:'充电曲线对比',description:'对照两次充电的功率、温度与耗时'},
      {id:'ledger',label:'充电账本',description:'充电费用、桩端电量与实际电价'}
    ]},
    {name:'车辆',page:'car',tools:[
      {id:'life',label:'生活账本',description:'保险、停车费用、洗车支出与保养待办'}
    ]},
    {name:'设置',page:'settings',tools:[
      {id:'rules',label:'自定义提醒',description:'电量条件、提醒规则与触发记录'},
      {id:'quality',label:'数据质量雷达',description:'采集诊断：覆盖、延迟、重复缓存与缺口'}
    ]},
    {name:'行程',page:'tracks',tools:[{id:'routes',label:'常走路线对比',description:'方向、用时、里程与有效耗电样本'}]},
    {name:'用车日历',page:'calendar',tools:[{id:'calendar',label:'用车日历',description:'按日期查看行程、充电与停车'}]},
    {name:'用车周报',page:'report',tools:[{id:'report',label:'用车周报',description:'周期里程、能耗估算、日趋势与样本'}]}
  ];
  const toolsFor=section=>toolGroups.filter(group=>(group.page || 'insights')===section).flatMap(group=>group.tools);

  function create({getState,request,escape:esc,active,review,navigate,dictionary}) {
    let tab='research', section='insights', toolQuery='', toolsExpanded=false;
    const groups=()=>toolGroups.filter(group=>(group.page || 'insights')===section);
    const automaticPage=root.AutomaticInsightsPage.create({getState,request,escape:esc,active:()=>active() && tab==='automatic',time,navigate});
    const reportPage=root.UsageReportPage.create({getState,request,escape:esc,active:()=>active() && tab==='report',time});
    const ledgerPage=root.ChargeLedgerPage.create({getState,request,escape:esc,active:()=>active() && tab==='ledger',time});
    const rulesPage=root.CustomRemindersPage.create({getState,request,escape:esc,active:()=>active() && tab==='rules',time});
    const chargeComparisonPage=root.ChargeComparisonPage.create({getState,request,escape:esc,active:()=>active() && tab==='charge-comparison',time});
    const labPage=root.ParameterExperimentsPage.create({getState,request,escape:esc,active:()=>active() && tab==='lab',time});
    const researchPage=root.VehicleResearchPage.create({getState,request,escape:esc,active:()=>active() && tab==='research',time,experiment:openExperiment,review,diagnose:()=>navigate('settings','quality')});
    const calendarPage=root.UsageCalendarPage.create({getState,request,escape:esc,active:()=>active() && tab==='calendar',time,navigate:openDate});
    const lifePage=root.VehicleLifePage.create({getState,request,escape:esc,active:()=>active() && tab==='life',time});
    const qualityPage=root.DataQualityPage.create({getState,request,escape:esc,active:()=>active() && tab==='quality',time,navigate:openDate});
    const routesPage=root.TravelInsightsPage.create({kind:'routes',getState,request,escape:esc,active:()=>active()&&tab==='routes',time,navigate});
    const reviewPage=root.TravelInsightsPage.create({kind:'review',getState,request,escape:esc,active:()=>active()&&tab==='review',time,navigate});
    const views={routes:routesPage,review:reviewPage,fields:dictionary,automatic:automaticPage,research:researchPage,report:reportPage,ledger:ledgerPage,rules:rulesPage,'charge-comparison':chargeComparisonPage,lab:labPage,calendar:calendarPage,life:lifePage,quality:qualityPage};
    let node=null, owner='', date=today(), loadedDate='', records=[], cursor=null, index=0;
    let detail=null, baseline=null, comparison=null, loading=false, detailLoading=false, compareLoading=false;
    let error='', detailError='', compareError='', query='', fieldPage=0;
    let listSerial=0, detailSerial=0, compareSerial=0, selectTimer;

    function reset() {
      records=[];cursor=null;index=0;detail=null;baseline=null;comparison=null;loadedDate='';
      loading=false;detailLoading=false;compareLoading=false;error='';detailError='';compareError='';
      listSerial++;detailSerial++;compareSerial++;clearTimeout(selectTimer);
    }
    function context() {return getState()?.insights_context || '';}
    function openField(path){tab='research';toolQuery='';paint();researchPage.openField(path);}
    function openExperiment(selection){tab='lab';toolQuery='';paint();labPage.openEvidence(selection);}
    function openTool(id){if(['calendar','report'].includes(id)&&section!==id){navigate(id,id);return true;}if(!toolsFor(section).some(tool=>tool.id===id))return false;tab=id;toolQuery='';toolsExpanded=false;paint();return true;}
    function openDate(view,target){
      const destination=toolGroups.find(group=>group.tools.some(tool=>tool.id===view))?.page || 'insights';
      if(destination!==section){navigate(destination,view,target);return;}
      tab=view;toolQuery='';
      if(view==='time'){date=target;reset();paint();}
      else{
        paint();
        const field=node.querySelector({ledger:'#ledger-month',routes:'#routes-month',review:'#review-date',report:'#report-date',calendar:'#calendar-month'}[view]||'input[type="date"]');
        if(field){field.value=field.type==='month'?target.slice(0,7):target;field.dispatchEvent(new Event('input',{bubbles:true}));}
      }
    }
    function valid(serial, current, identity) {return serial===current && owner===identity && identity===context();}
    function button(label, action, disabled=false) {return `<button class="button secondary" id="insight-${action}" data-insight="${action}" ${disabled?'disabled':''}>${label}</button>`;}
    function badges(record) {
      return `<span class="insight-badge">${changes[record.change] || '未知'}</span>${record.flags.map(flag=>`<span class="insight-badge insight-warning">${esc(flags[flag] || flag)}</span>`).join('')}${record.gap_seconds?`<span class="insight-badge insight-warning">与上一条采集相隔 ${Math.round(record.gap_seconds/60)} 分钟</span>`:''}`;
    }
    function saveFocus() {
      const el=document.activeElement;
      return el?.id?.startsWith('insight-') ? {id:el.id,start:el.selectionStart,end:el.selectionEnd} : null;
    }
    function restoreFocus(saved) {
      const el=saved && document.getElementById(saved.id);
      if(el && !el.disabled){el.focus({preventScroll:true});if(saved.start!=null)el.setSelectionRange(saved.start,saved.end);}
    }
    function navigation() {
      const visible=groups(), toolCount=visible.reduce((total,group)=>total+group.tools.length,0);
      return `<aside class="insight-navigation"><div class="insight-mobile-tools"><label>当前研究工具<select id="insight-tool-select" aria-label="当前研究工具">${section==='insights'?'':'<option value="">选择子功能</option>'}${visible.map(g=>`<optgroup label="${g.name}">${g.tools.map(t=>`<option value="${t.id}">${t.label}</option>`).join('')}</optgroup>`).join('')}</select></label><button class="button secondary" data-insight="toggle-tools" aria-controls="insight-tool-directory" aria-expanded="${toolsExpanded}">查找工具</button></div><div id="insight-tool-directory" data-expanded="${toolsExpanded}"><div class="insight-nav-heading"><strong>${section==='insights'?'研究工具':'相关工具'}</strong><span id="insight-tool-count">${toolCount} 项</span></div>
        <div class="insight-tool-search"><label for="insight-tool-search">${section==='insights'?'查找研究工具':'查找子功能'}</label><div><input id="insight-tool-search" type="search" value="${esc(toolQuery)}" placeholder="搜名称或用途"><button id="insight-tool-clear" data-insight="clear-tools" aria-label="清空工具搜索" title="清空工具搜索">×</button></div></div>
        <nav class="insight-tabs" aria-label="${section==='insights'?'用车研究工具':'相关工具'}">${visible.map((group,i)=>`<section data-insight-group="${i}" aria-labelledby="insight-group-${i}"><h2 id="insight-group-${i}">${group.name}</h2><div>${group.tools.map(tool=>`<button data-insight-view="${tool.id}" aria-pressed="${tab===tool.id}" title="${tool.description}">${tool.label}</button>`).join('')}</div></section>`).join('')}</nav>
        <p class="insight-nav-empty" role="status" hidden>没有匹配的工具，请清空搜索后重试。</p></div></aside>`;
    }
    function updateNavigation() {
      const term=toolQuery.trim().toLowerCase();
      const visible=groups(), toolCount=visible.reduce((total,group)=>total+group.tools.length,0);
      let count=0;
      node.querySelector('#insight-tool-search').value=toolQuery;
      node.querySelector('#insight-tool-select').value=tab;
      node.querySelector('#insight-tool-directory').dataset.expanded=String(toolsExpanded);
      node.querySelector('[data-insight=toggle-tools]').setAttribute('aria-expanded',String(toolsExpanded));
      for(const [i,group] of visible.entries()){
        let groupCount=0;
        for(const tool of group.tools){
          const el=node.querySelector(`[data-insight-view="${tool.id}"]`);
          el.hidden=!!term && !`${group.name} ${tool.label} ${tool.description}`.toLowerCase().includes(term);
          el.setAttribute('aria-pressed',String(tab===tool.id));
          if(!el.hidden)groupCount++;
        }
        node.querySelector(`[data-insight-group="${i}"]`).hidden=!groupCount;
        count+=groupCount;
      }
      node.querySelector('#insight-tool-count').textContent=term?`${count} / ${toolCount} 项`:`${toolCount} 项`;
      node.querySelector('.insight-nav-empty').hidden=count>0;
    }
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected || !active())return;
      const focus=saveFocus();
      if(!node.querySelector('.insight-layout')){
        node.innerHTML=`<div class="insight-layout">${navigation()}<div class="insight-content"></div></div>`;
      }
      updateNavigation();
      const content=node.querySelector('.insight-content');
      if(!tab){content.innerHTML='<section class="card insight-panel"><h2>选择子功能</h2><p>从上方快捷入口或这里的工具列表打开。</p></section>';return;}
      if(views[tab]){
        content.innerHTML=`<div id="${tab}-workspace"></div>`;
        views[tab].mount(node.querySelector(`#${tab}-workspace`));
        restoreFocus(focus);
        return;
      }
      content.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">车辆时间机</span><h2>回到每一次观测</h2><p>看当时的车况，比较前后的变化。</p></div><span class="insight-source">本机归档 · 北京时间</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>归档日期<input id="insight-date" type="date" value="${esc(date)}"></label>${button('查看归档','load',!owner || !date)}<span id="insight-count" role="status">${loading?'正在读取…':loadedDate?`${loadedDate} · 已载入 ${records.length} 条${cursor?'，还有更多':''}`:'选择日期查看'}</span></div>
        <p class="insight-note">按采集日期查找。每条保留独立的车辆时间；重复读取不代表车辆产生新数据。</p>
        ${!owner?'<p class="insight-empty">连接车辆账号并取得当前车辆绑定后，可查看对应归档。</p>':''}
        ${error?`<div class="notice error" role="alert">${esc(error)}</div>`:''}
        ${records.length?`<div class="insight-timeline"><label for="insight-slider">观测时间轴</label><input id="insight-slider" type="range" min="0" max="${records.length-1}" value="${index}" step="1"><div class="insight-stepper">${button('上一条观测','previous',index===0)}<span id="insight-selection" aria-live="polite"></span>${button('下一条观测','next',index===records.length-1)}</div><label class="insight-select-label">选择观测<select id="insight-select" aria-label="选择观测">${records.map((record,i)=>`<option value="${i}" ${i===index?'selected':''}>${i+1} · ${esc(time(record.observed_at))} · ${changes[record.change]}</option>`).join('')}</select></label></div>${cursor?`<div class="insight-load-more">${button('加载更多观测','more',loading)}</div>`:''}`:loadedDate && !loading?'<div class="insight-empty"><h3>这一天还没有归档观测</h3><p>未启用归档、暂停或未成功采集，都会留下空白。没有记录不等于车辆未使用。</p></div>':''}
        </section>
        <div id="insight-snapshot" aria-live="polite"></div><div id="insight-actions" class="insight-actions"></div>
        <div id="insight-comparison"></div><div id="insight-fields"></div>
        <p class="insight-note">超过 10 分钟没有采集记录会标出间隔。正常采样间隔以设置页为准，车辆上传和故障退避也会影响观测间隔。只展示已归档内容，不补造车况。</p>`;
      paintSelection();paintDetails();paintComparison();restoreFocus(focus);
    }
    function paintSelection() {
      const record=records[index], label=node?.querySelector('#insight-selection');
      if(!record || !label)return;
      label.textContent=`${index+1} / ${records.length} · ${time(record.observed_at)}`;
      node.querySelector('#insight-slider').value=index;
      node.querySelector('#insight-slider').setAttribute('aria-valuetext',`${index+1}，采集于 ${time(record.observed_at)}`);
      node.querySelector('#insight-select').value=index;
      node.querySelector('#insight-previous').disabled=index===0;
      node.querySelector('#insight-next').disabled=index===records.length-1;
    }
    function paintDetails(){
      return root.RefreshView?root.RefreshView.preserve(node,paintDetailsContent):paintDetailsContent();
    }
    function paintDetailsContent(){
      const container=node?.querySelector('#insight-snapshot');
      if(!container)return;
      const record=records[index];
      if(!record){container.innerHTML='';paintActions();paintFields();return;}
      const summary=detail?.record.key===record.key ? detail.summary : null;
      const labels={battery:'动力电池',range:'预估续航',inside:'座舱温度',outside:'车外温度',lock:'门锁',doors:'车门',windows:'车窗',charging:'充电状态'};
      container.innerHTML=`<section class="card insight-panel"><div class="insight-heading"><h3>这一刻的车况</h3><div class="insight-badges">${badges(record)}</div></div><div class="insight-times"><span>车辆更新<strong>${esc(time(record.state_time))}</strong></span><span>云端读取<strong>${esc(time(record.fetched_at))}</strong></span><span>归档采集<strong>${esc(time(record.observed_at))}</strong></span></div>
        ${detailError?`<div class="notice error" role="alert">${esc(detailError)} ${button('重试这条观测','retry-detail')}</div>`:detailLoading?'<p class="insight-note">正在读取这条观测…</p>':''}
        ${summary?`<div class="insight-metrics">${Object.entries(labels).map(([key,label])=>`<div><span>${label}</span><strong>${esc(summary[key])}</strong></div>`).join('')}</div>`:''}</section>`;
      paintActions();paintFields();
    }
    function paintActions() {
      const el=node?.querySelector('#insight-actions');if(!el)return;
      el.innerHTML=records.length?`${button('设为对比起点','pin',!detail || detailLoading)}${button('与起点比较','compare',!detail || detailLoading || !baseline || baseline.key===detail.record.key || compareLoading)}${baseline?`<span>起点：${esc(time(baseline.observed_at))}</span>${button('清除对比','clear')}`:'<span>选一条作为起点，再拖到另一条比较。可跨日期选择。</span>'}`:'';
    }
    function paintFields() {
      const el=node?.querySelector('#insight-fields');if(!el)return;
      if(!detail || detailLoading){el.innerHTML='';return;}
      const focus=saveFocus(), term=query.trim().toLowerCase();
      const fields=detail.fields.filter(field=>field.status!=='missing' && (!term || `${field.name} ${field.path} ${field.group}`.toLowerCase().includes(term)));
      const pages=Math.max(1,Math.ceil(fields.length/24));fieldPage=Math.min(fieldPage,pages-1);
      el.innerHTML=`<section class="card insight-panel"><div class="insight-heading"><h3>当时返回的参数</h3><label>搜索历史参数<input type="search" id="insight-search" value="${esc(query)}" placeholder="中文名称 / 字段路径"></label></div><p class="insight-note">匹配 ${fields.length} 项 · 安全目录 ${detail.counts.total} 项，本次返回 ${detail.counts.returned} 项。未返回的值不从其他时刻补入。</p>
        <div class="insight-fields">${fields.slice(fieldPage*24,fieldPage*24+24).map(field=>`<article data-field="${esc(field.path)}"><span>${esc(field.name)}</span><strong>${esc(field.value)}</strong><small>原值 ${esc(field.raw)} · ${esc(field.evidence)}</small><small>${esc(field.time_source)} ${esc(time(field.updated_time))}</small></article>`).join('') || '<p>没有匹配参数。</p>'}</div><div class="insight-pagination">${button('上一页参数','fields-prev',fieldPage===0)}<span>${fieldPage+1} / ${pages}</span>${button('下一页参数','fields-next',fieldPage+1===pages)}</div></section>`;
      restoreFocus(focus);
    }
    function paintComparison(){
      return root.RefreshView?root.RefreshView.preserve(node,paintComparisonContent):paintComparisonContent();
    }
    function paintComparisonContent(){
      const el=node?.querySelector('#insight-comparison');if(!el)return;
      if(!comparison && !compareError && !compareLoading){el.innerHTML='';return;}
      el.innerHTML=`<section class="card insight-panel"><h3>前后变化</h3>${compareError?`<p role="alert">${esc(compareError)}</p>`:compareLoading?'<p>正在比较两条观测…</p>':`<p class="insight-note">起点采集 ${esc(time(comparison.before.observed_at))} → 终点采集 ${esc(time(comparison.after.observed_at))}<br>车辆时间 ${esc(time(comparison.before.state_time))} → ${esc(time(comparison.after.state_time))}。${comparison.changes.length} 项变化；不据此推断因果。</p>
        <div class="insight-diff">${comparison.changes.map(field=>`<article data-change="${esc(field.path)}"><strong>${esc(field.name)}${field.display_limited?'<small class="insight-truncated">显示值已简化；完整值存在差异</small>':''}</strong><div><span>起点</span><b>${esc(field.before.value)}</b><small>原值 ${esc(field.before.raw)}</small></div><div><span>终点</span><b>${esc(field.after.value)}</b><small>原值 ${esc(field.after.raw)}</small></div></article>`).join('') || '<p>两条观测的安全参数值没有变化。</p>'}</div>`}</section>`;
    }
    async function load(more=false) {
      if(!owner || !date)return;
      const identity=owner, token=++listSerial, selectedDate=more?loadedDate:date;
      if(!more){records=[];index=0;cursor=null;detail=null;comparison=null;compareError='';detailSerial++;compareSerial++;clearTimeout(selectTimer);}
      loading=true;error='';loadedDate=selectedDate;paint();
      try {
        const result=await request(`/api/insights/timeline?date=${encodeURIComponent(selectedDate)}${more && cursor?'&cursor='+encodeURIComponent(cursor):''}`);
        if(!valid(token,listSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，等待页面同步后重试。');
        records=more?records.concat(result.items.filter(item=>!records.some(old=>old.key===item.key))):result.items;
        cursor=result.next_cursor;
        if(records.length && !more)select(0);
      } catch(failure) {if(valid(token,listSerial,identity))error=failure.message;}
      finally {if(valid(token,listSerial,identity)){loading=false;if(tab==='time')paint();}}
    }
    function select(next, debounce=false) {
      if(!records[next])return;
      index=next;detail=null;detailError='';detailLoading=true;fieldPage=0;
      const identity=owner, token=++detailSerial, key=records[index].key;
      clearTimeout(selectTimer);paintSelection();paintDetails();
      const fetchDetail=async()=>{
        try {
          const result=await request('/api/insights/snapshot?id='+encodeURIComponent(key));
          if(!valid(token,detailSerial,identity))return;
          if(result.context!==identity)throw Error('账号或车辆已切换，请重新选择。');
          detail=result;
        } catch(failure){if(valid(token,detailSerial,identity))detailError=failure.message;}
        finally {if(valid(token,detailSerial,identity)){detailLoading=false;if(active())paintDetails();}}
      };
      if(debounce)selectTimer=setTimeout(fetchDetail,150);else fetchDetail();
    }
    async function compare() {
      if(!baseline || !detail)return;
      const identity=owner, token=++compareSerial;
      const before=baseline.key, after=detail.record.key;
      comparison=null;compareError='';compareLoading=true;paintActions();paintComparison();
      try {
        const result=await request(`/api/insights/compare?before=${encodeURIComponent(before)}&after=${encodeURIComponent(after)}`);
        if(!valid(token,compareSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新比较。');
        comparison=result;
      } catch(failure){if(valid(token,compareSerial,identity))compareError=failure.message;}
      finally {if(valid(token,compareSerial,identity)){compareLoading=false;if(active()){paintActions();paintComparison();}}}
    }
    function mount(container, nextSection='insights') {
      const changed=context()!==owner, sectionChanged=section!==nextSection, remount=node!==container;
      if(sectionChanged){section=nextSection;tab=section==='insights'?'research':['calendar','report'].includes(section)?section:'';toolQuery='';toolsExpanded=false;}
      if(changed){owner=context();toolQuery='';toolsExpanded=false;reset();}
      node=container;
      node.classList.toggle('standalone-task',section!=='insights');
      if(sectionChanged)node.innerHTML='';
      if(changed || remount || sectionChanged)paint();
      if(views[tab])views[tab].mount(node.querySelector(`#${tab}-workspace`));
    }
    function handle(event) {
      if(!active() || !node?.contains(event.target))return false;
      const el=event.target;
      const view=event.type==='click' && el.closest('[data-insight-view]');
      if(view || (event.type==='change' && el.id==='insight-tool-select')){
        const next=view?view.dataset.insightView:el.value;
        toolQuery='';toolsExpanded=false;
        if(tab!==next){tab=next;paint();}else updateNavigation();
        const selector=node.querySelector('#insight-tool-select');
        if(selector.checkVisibility())selector.focus({preventScroll:true});
          return true;
      }
      if(event.type==='input' && el.id==='insight-tool-search'){toolQuery=el.value;updateNavigation();return true;}
      if(views[tab]?.handle(event))return true;
      if(event.type==='input' && el.id==='insight-date'){date=el.value;reset();paint();return true;}
      if(event.type==='input' && el.id==='insight-slider'){select(Number(el.value),true);return true;}
      if(event.type==='input' && el.id==='insight-search'){query=el.value;fieldPage=0;paintFields();return true;}
      if(event.type==='change' && el.id==='insight-select'){select(Number(el.value));return true;}
      if(event.type!=='click')return false;
      const target=el.closest('[data-insight]');if(!target || target.disabled)return false;
      switch(target.dataset.insight){
        case 'toggle-tools':toolsExpanded=!toolsExpanded;updateNavigation();if(toolsExpanded)node.querySelector('#insight-tool-search').focus({preventScroll:true});break;
        case 'clear-tools':toolQuery='';updateNavigation();node.querySelector('#insight-tool-search').focus({preventScroll:true});break;
        case 'load':load();break;
        case 'more':load(true);break;
        case 'previous':select(index-1);break;
        case 'next':select(index+1);break;
        case 'retry-detail':select(index);break;
        case 'pin':baseline=detail.record;comparison=null;compareError='';compareSerial++;compareLoading=false;paintActions();paintComparison();break;
        case 'compare':compare();break;
        case 'clear':baseline=null;comparison=null;compareError='';compareSerial++;compareLoading=false;paintActions();paintComparison();break;
        case 'fields-prev':fieldPage--;paintFields();break;
        case 'fields-next':fieldPage++;paintFields();break;
      }
      return true;
    }
    return {mount,handle,openField,openExperiment,openTool,openDate,openLedgerEvent:ledgerPage.openEvent,currentTool:()=>tab};
  }
  root.InsightsPage={create,toolsFor};
})(window);
