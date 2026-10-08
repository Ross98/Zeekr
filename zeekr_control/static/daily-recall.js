'use strict';
const recallTypes={trip:'行程',parking:'停车观测',charge:'充电'};
const recallSources={manual:'人工确认',commute:'通勤规则',address:'自动地址',unknown:'未知'};
let recallCorrection=null,recallHistory=null,recallYear=null,recallYearSerial=0,recallLedgerReturn=null;
function recallNeedsReview(row){return ['start','end'].some(side=>row[side+'_place']?.issues?.some(i=>['adjacent_conflict','candidate_conflict','missing_position'].includes(i)));}
function recallSummary(){
  const d=localTrips?.timeline;if(!d)return '';
  const s=d.summary,c=d.coverage;
  return `<div class="recall-summary" aria-label="当天摘要"><span>结束行程里程 <strong>${esc(tripNumber(s.distance_km,' km'))}</strong></span><span>观测驾驶时长 <strong>${esc(tripDuration(s.duration_seconds))}</strong></span><span>充电 <strong>${s.charge_count} 次</strong></span><span>已填账单 <strong>${esc(tripNumber(s.actual_cents===null?null:s.actual_cents/100,' 元'))}</strong></span><span>待补账 <strong>${s.pending_count} 次</strong></span>${d.records.some(recallNeedsReview)?`<button class="button quiet" data-recall-review>地点待核对 ${d.records.filter(recallNeedsReview).length} 条</button>`:''}</div><p class="section-note">${{missing:'无归档观测；不代表当天没用车。',limited:'仅重复或异常观测，覆盖受限。',observed:'有有效车辆时刻；不表示全天覆盖。',future:'未来日期。'}[c.coverage]||'覆盖未知。'}跨日里程归结束日；费用按账单日。</p>`;
}
function recallFacts(row){
  const place=side=>{const p=row[side+'_place'];if(!p)return '';return `<div class="recall-place"><span>${side==='start'?'起点':'终点'} ${esc(p.label)} · ${recallSources[p.source]||'未知'}${p.decision==='rejected'?' · 已拒绝匹配':''}${p.issues?.some(i=>['adjacent_conflict','candidate_conflict','missing_position'].includes(i))?' · 待核对':''}</span>${p.key?`<button class="button quiet" data-recall-correct="${side}">修正地点</button><button class="button quiet" data-recall-history="${side}">地点历史</button>`:'<span class="subtle">缺少可信位置</span>'}</div>`;};
  return `<div class="local-trip-intro"><h2>${recallTypes[row.type]||'行程'}${row.cross_midnight?' · 跨午夜':''}</h2><p>记录起点 ${esc(tripTime(row.start_time))}<br>记录终点 ${esc(tripTime(row.end_time))}</p>${place('start')}${place('end')}<p>观测时长 ${esc(tripDuration(row.duration_seconds))}${row.type==='trip'?` · 里程 ${esc(tripNumber(row.distance_km,' km'))}`:''}</p>${row.partial?'<p class="subtle">部分记录；缺失范围不推断。</p>':''}${row.reason_labels?`<p class="subtle">${row.reason_labels.map(esc).join('；')}</p>`:''}${row.type==='charge'?`<p>账单金额 ${esc(tripNumber(row.bill?.actual_cents==null?null:row.bill.actual_cents/100,' 元'))}</p><button class="button secondary" data-recall-ledger>打开账本编辑</button>`:''}<div id="recall-correction"></div><div id="recall-history"></div><button class="button secondary recall-map-jump" data-recall-map>查看地图</button></div>`;
}
function recallContext(){return [state?.insights_context,trackDate,localTrips?.selection].join('|');}
function recallCorrectionPaint(){
  const el=$('#recall-correction'),c=recallCorrection;if(!el||!c||c.context!==recallContext())return;
  el.innerHTML=`<form id="recall-correction-form" class="recall-editor"><h3>修正${c.side==='start'?'起点':'终点'}地点</h3><label>操作<select id="recall-decision" class="select"><option value="confirm">确认当前名称</option><option value="assign">改归属名称</option><option value="reject">拒绝自动名称</option></select></label><label>已有地点<select id="recall-target" class="select"><option value="">仅修正本次名称</option>${(localTrips.timeline.known_places||[]).map(p=>`<option value="${esc(p.key)}">${esc(p.name)}</option>`).join('')}</select></label><label>地点名称<input id="recall-name" class="input" maxlength="40" value="${esc(c.name)}"></label><label><input id="recall-remember" type="checkbox">拒绝时，此地点记住该否定</label><p class="subtle">默认只影响本次记录。拒绝名称，停车事实保留。</p><p id="recall-write-status" role="status">${esc(c.message||'')}</p><div class="recall-actions"><button type="submit" class="button secondary" ${c.busy?'disabled':''}>预览影响</button>${c.preview?'<button type="button" class="button" data-recall-save>保存修正</button>':''}<button type="button" class="button quiet" data-recall-cancel>取消</button></div></form>`;
  $('#recall-decision').value=c.action;$('#recall-target').value=c.targetKey||'';
  $('#recall-remember').checked=c.remember;
  $('#recall-correction-form').addEventListener('input',()=>{c.action=$('#recall-decision').value;c.name=$('#recall-name').value;c.remember=$('#recall-remember').checked;c.targetKey=$('#recall-target').value;c.preview=null;el.querySelector('[data-recall-save]')?.remove();});
  $('#recall-correction-form').addEventListener('submit',e=>{e.preventDefault();recallWrite('preview');});
}
async function recallWrite(operation){
  const c=recallCorrection,h=localTrips;if(!c||c.busy||c.context!==recallContext())return;
  if(operation==='save'&&!c.preview)return;
  const data={operation,date:trackDate,record_id:h.selection,side:c.side,action:c.action,name:c.name,remember:c.remember,target_key:c.targetKey,
    revision:h.timeline.correction_revision,context:h.timeline.context,preview_token:c.preview?.preview_token};
  c.busy=true;c.message='正在处理…';recallCorrectionPaint();
  try{const result=await api('/api/place-corrections',data);if(localTrips!==h||c.context!==recallContext()||result.context!==state?.insights_context)return;
    if(operation==='preview'){c.preview=result;c.message=`本查询范围影响 ${result.affected_count} 条记录。${result.remember?'后续同地点匹配也会避开此名称。':''}`;}
    else{recallCorrection=null;recallHistory=null;recallYear=null;await loadLocalTrips(true);if(localTrips===h){renderLocalTripFacts();}}
  }catch(error){if(c.context===recallContext()){c.message=error.message;c.preview=null;}}
  finally{c.busy=false;recallCorrectionPaint();}
}
async function recallLoadHistory(side,cursor=null){
  const h=localTrips,p=h?.selected?.[side+'_place'];if(!p?.key)return;
  const context=recallContext(),personalRevision=window.recallPersonalRevision,end=trackDate,start=beijingDate(new Date(end+'T12:00:00+08:00').getTime()-30*86400000);
  const el=$('#recall-history');el.innerHTML='<p role="status">正在读取地点历史…</p>';
  try{const d=await api(`/api/place-history?start=${start}&end=${end}&key=${encodeURIComponent(p.key)}${cursor?'&cursor='+encodeURIComponent(cursor):''}`);
    if(localTrips!==h||context!==recallContext()||personalRevision!==window.recallPersonalRevision||d.context!==state?.insights_context)return;
    recallHistory={side,data:d};el.innerHTML=`<div class="recall-history"><h3>近 31 天 · ${esc(p.label)}</h3><p>${d.count} 条关联记录；行程端点不算完整停留。</p>${d.records.map(r=>`<button class="button quiet" data-recall-record="${esc(r.id)}" data-recall-date="${r.date}">${esc(tripTime(r.start_time))} · ${recallTypes[r.type]} · ${esc(tripDuration(r.duration_seconds))}</button>`).join('')||'<p>没有关联记录。</p>'}${d.next_cursor?'<button class="button secondary" data-recall-history-next>下一页</button>':''}</div>`;
  }catch(error){if(context===recallContext())el.innerHTML=`<p role="alert">${esc(error.message)}</p>`;}
}
function recallOpenDay(date,id='day'){
  page='tracks';sectionTask='';trackSource='local';trackDate=date;render();const h=syncLocalTrips();h.selection='day';h.restoreSelection=id;
  loadLocalTrips(true).then(()=>{if(localTrips===h&&showPosition)loadLocalRoute();});window.scrollTo({top:0,behavior:'instant'});
}
async function recallLoadYear(){
  const year=$('#recall-year')?.value,context=state?.insights_context,serial=++recallYearSerial;
  if(!/^20\d{2}$/.test(year||''))return;
  $('#recall-year-result').innerHTML='<p role="status">正在读取全年统计…</p>';
  try{const d=await api('/api/year-review?year='+year);if(serial!==recallYearSerial||context!==state?.insights_context||d.context!==context)return;
    recallYear={context,data:d,mode:$('#recall-year-mode')?.value||'distance'};recallPaintYear();persistNavigation();
  }catch(e){if(serial===recallYearSerial&&context===state?.insights_context&&$('#recall-year-result'))$('#recall-year-result').innerHTML=`<p role="alert">${esc(e.message)}</p>`;}
}
function recallYearPanel(){
  const year=recallYear?.context===state?.insights_context?recallYear.data.year:beijingDate(Date.now()).slice(0,4);
  return `<details class="card recall-year-panel" data-detail="recall-year"><summary>年度用车回顾</summary><div class="recall-year-controls"><label>回顾年份<input id="recall-year" class="input" type="number" min="2000" max="2099" value="${year}"></label><label>热力图显示<select id="recall-year-mode" class="select"><option value="distance">里程</option><option value="cost">已记账费用</option></select></label><button class="button secondary" data-recall-year-load>读取年度回顾</button></div><div id="recall-year-result"></div></details>`;
}
function recallPaintYear(){
  return window.RefreshView?window.RefreshView.preserve($('#main'),recallPaintYearContent):recallPaintYearContent();
}
function recallPaintYearContent(){
  const el=$('#recall-year-result'),saved=recallYear;if(!el||!saved||saved.context!==state?.insights_context)return;
  const d=saved.data,mode=saved.mode;$('#recall-year-mode').value=mode;
  const value=day=>mode==='cost'?day.actual_cents:day.distance_km;
  const max=Math.max(1,...d.days.map(day=>value(day)||0));
  el.innerHTML=`<div class="recall-summary"><span>有行程记录 <strong>${d.totals.usage_days} 天</strong></span><span>里程 <strong>${esc(tripNumber(d.totals.distance_km,' km'))}</strong></span><span>已记账 <strong>${esc(tripNumber(d.totals.actual_cents===null?null:d.totals.actual_cents/100,' 元'))}</strong></span><span>金额未知 <strong>${d.totals.unpriced_count} 笔</strong></span><span>待补账 <strong>${d.totals.pending_count} 次</strong></span></div><p class="subtle">无归档、观测受限、有效观测、未来日期分别标记。未记录到行程，不代表没有用车。</p><div class="recall-year-months">${d.months.map(m=>`<section><h3>${m.month}</h3><div class="recall-heatmap">${d.days.filter(day=>day.date.startsWith(m.month)).map(day=>{
    const v=value(day),amount=tripNumber(v===null?null:mode==='cost'?v/100:v,mode==='cost'?' 元':' km');
    const coverage={missing:'无归档',limited:'观测受限',observed:'有效观测',future:'未来'}[day.coverage];
    const label=`${day.date}，${amount}，${coverage}，${day.trip_count?'有行程记录':'未记录到行程'}`;
    return `<button class="recall-heat-day ${day.coverage} ${v===null?'unknown-value':''} level-${v===null?0:Math.min(4,Math.ceil(v/max*4))}" data-recall-date="${day.date}" aria-label="${esc(label)}" title="${esc(label)}">${Number(day.date.slice(-2))}<small>${{missing:'缺',limited:'限',future:'未',observed:'观'}[day.coverage]}</small></button>`;
  }).join('')}</div><p class="subtle">${m.trip_count} 趟 · ${esc(tripNumber(m.distance_km,' km'))} · ${esc(tripNumber(m.actual_cents===null?null:m.actual_cents/100,' 元'))}</p></section>`).join('')}</div><h3>常停车地点</h3><p class="subtle">按观测停车片段次数；断档不合并，也不声称完整停车次数。</p>${(d.frequent_parking_places||[]).map(p=>`<button class="button quiet" data-recall-date="${p.date}" data-recall-record="${esc(p.record_id)}">${esc(p.label)} · ${p.count} 段</button>`).join('')||'<p>没有可命名的停车观测。</p>'}<h3>常到达地点</h3><p class="subtle">按行程到达次数，不冒充完整停车次数。</p>${d.frequent_places.map(p=>`<p>${esc(p.label)} · ${p.arrivals} 次到达</p>`).join('')||'<p>没有可统计的地点。</p>'}`;
}
async function recallAction(target){
  if(target.hasAttribute('data-recall-review')){const row=localTrips.events.find(recallNeedsReview);if(row){handleLocalTripAction({dataset:{localTrip:row.id}});$(`[data-local-trip="${CSS.escape(row.id)}"]`)?.focus({preventScroll:true});$('#local-trip-facts').scrollIntoView({block:'start'});}return true;}
  if(target.hasAttribute('data-recall-year-load')){recallLoadYear();return true;}
  if(target.dataset.recallDate){recallOpenDay(target.dataset.recallDate,target.dataset.recallRecord||'day');return true;}
  if(target.dataset.recallCorrect){const p=localTrips.selected[target.dataset.recallCorrect+'_place'];recallCorrection={context:recallContext(),side:target.dataset.recallCorrect,name:p.label,action:'assign',remember:false};recallCorrectionPaint();return true;}
  if(target.dataset.recallHistory){recallLoadHistory(target.dataset.recallHistory);return true;}
  if(target.hasAttribute('data-recall-history-next')){recallLoadHistory(recallHistory.side,recallHistory.data.next_cursor);return true;}
  if(target.hasAttribute('data-recall-save')){recallWrite('save');return true;}
  if(target.hasAttribute('data-recall-cancel')){recallCorrection=null;$('#recall-correction').innerHTML='';return true;}
  if(target.hasAttribute('data-recall-map')){$('#local-trip-route').scrollIntoView({block:'start',behavior:'smooth'});return true;}
  if(target.hasAttribute('data-recall-ledger')){const row=localTrips.selected;recallLedgerReturn={date:trackDate,id:row.id,context:state?.insights_context};page='books';sectionTask='ledger';render();insightsPage.openDate('ledger',row.bill?.date||row.date);insightsPage.openLedgerEvent(row.id,row.bill?.date||row.date);return true;}
  if(target.hasAttribute('data-recall-return')){if(recallLedgerReturn?.context===state?.insights_context)recallOpenDay(recallLedgerReturn.date,recallLedgerReturn.id);return true;}
  if(target.hasAttribute('data-recall-undo')){const h=localTrips;try{await api('/api/place-corrections',{operation:'undo',context:h.timeline.context,revision:h.timeline.correction_revision});if(h===localTrips){recallYear=null;await loadLocalTrips(true);}}catch(e){h.listError=e.message;renderLocalTripList();}return true;}
  return false;
}
document.addEventListener('click',e=>{const target=e.target.closest('[data-recall-review],[data-recall-return],[data-recall-year-load],[data-recall-date],[data-recall-correct],[data-recall-history],[data-recall-history-next],[data-recall-save],[data-recall-cancel],[data-recall-map],[data-recall-ledger],[data-recall-undo]');if(target){e.preventDefault();recallAction(target);}});
document.addEventListener('change',e=>{if(e.target.id==='recall-year-mode'&&recallYear){recallYear.mode=e.target.value;recallPaintYear();persistNavigation();}});

window.recallCanReturn=()=>recallLedgerReturn?.context===state?.insights_context;

window.recallPersonalRevision=0;
window.recallInvalidate=()=>{const reload=recallYear?.context===state?.insights_context&&$('.recall-year-panel')?.open;window.recallPersonalRevision++;recallYearSerial++;recallYear=null;recallHistory=null;if($('#recall-year-result'))$('#recall-year-result').innerHTML='<p role="status">数据已更新，请重新读取年度回顾。</p>';if(reload)recallLoadYear();};
