'use strict';
const recallTypes={trip:'行程',parking:'停车观测',charge:'充电'};
const recallSources={manual:'人工确认',commute:'通勤规则',address:'自动地址',unknown:'未知'};
let recallCorrection=null,recallHistory=null,recallYear=null,recallYearSerial=0,recallLedgerReturn=null;
function recallNeedsReview(row){return ['start','end'].some(side=>row[side+'_place']?.issues?.some(i=>['adjacent_conflict','candidate_conflict','missing_position'].includes(i)));}
function recallSummary(){
  const d=localTrips?.timeline;if(!d)return '';
  return window.LocalTripVisuals.summary(d,trackDate)+(d.records.some(recallNeedsReview)?`<button class="button quiet" data-recall-review>地点待核对 ${d.records.filter(recallNeedsReview).length} 条</button>`:'');
}
// Place names and coordinate provenance are separate: a confirmed name can
// still refer to an endpoint inferred from parking evidence.
const recallParkingGapNumber=new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2});
function recallParkingGapDuration(seconds){
  if(seconds<60)return `${recallParkingGapNumber.format(seconds)} 秒`;
  const minutes=Math.round(seconds/60);
  return minutes>=60?`${Math.floor(minutes/60)} 小时 ${minutes%60} 分钟`:`${recallParkingGapNumber.format(seconds/60)} 分钟`;
}
function recallParkingEvidence(row,side){
  const evidence=row[side+'_place_evidence'];
  if(evidence?.source==='parking_reference')return `<div data-recall-place-evidence="${side}"><p>推定地点：停车前可信定位与停车参考坐标匹配同一已保存地点。</p><p class="subtle">参考定位 ${esc(tripTime(evidence.reference_time))} · 距停车起点 ${esc(tripDuration(evidence.sampling_gap_seconds))} · 坐标相距 ${esc(tripNumber(evidence.distance_m,' 米'))}。不作为可信 GPS，不补算采样缺口。</p></div>`;
  if(evidence?.source!=='parking_inferred')return '';
  const label=side==='start'?'起点':'终点',when=side==='start'?'出发前':'到达后';
  const gap=evidence.sampling_gap_seconds;
  return `<div data-recall-place-evidence="${side}"><p class="subtle">${label}由${when}停车位置推定，非可信 GPS 定位。</p>${Number.isFinite(gap)&&gap>0?`<p class="subtle">${label}定位采样缺口约 ${esc(recallParkingGapDuration(gap))}，间隔内移动情况未知。</p>`:''}</div>`;
}
function recallParkingStatus(row){
  return `${row.parking_status==='parked'?'已确认停车':'停车待确认'}${row.open?' · 后续未观测':''}`;
}
function recallParkingDetails(row){
  if(row.type!=='parking')return '';
  const q=row.observation_quality||{},gaps=row.observation_gaps||[],phases=row.charging_phases||[];
  return `<div class="recall-parking-evidence"><p><strong>${recallParkingStatus(row)}</strong> · ${row.soc_drop==null?'停车耗电未知':`停车耗电 ${esc(tripNumber(row.soc_drop,' 个百分点'))}`}</p><p class="subtle">区间跨度不代表缺口内连续停车。P 档仅作静止佐证，缓存重复不增加有效观测。</p><details><summary>停车观测依据 · ${row.sample_count} 条有效观测</summary><p>P 档有效观测 ${row.p_gear_samples??0} 条 · 缓存重复读取 ${q.repeat_reads??0} 次</p><p>有效观测最大间隔 ${esc(tripDuration(q.max_gap_seconds??null))} · 未知区间 ${esc(tripDuration(q.unknown_seconds??null))}</p>${gaps.map(g=>`<p>数据缺口 ${esc(tripTime(g.start_time))} — ${esc(tripTime(g.end_time))} · ${esc(tripDuration(g.duration_seconds))}</p>`).join('')}${q.gaps_limited?'<p class="subtle">仅列前 50 处缺口。</p>':''}</details>${phases.length?`<details><summary>停车内充电 · ${phases.length} 段</summary>${phases.map(p=>`<p>${esc(tripTime(p.start_time))} — ${esc(tripTime(p.end_time))} · ${esc(tripDuration(p.duration_seconds))}</p>`).join('')}</details>`:''}</div>`;
}
function recallFacts(row){
  const place=side=>{const p=row[side+'_place'];if(!p)return '';return `<div class="recall-place"><span>${side==='start'?'起点':'终点'} ${esc(p.label)} · ${recallSources[p.source]||'未知'}${p.decision==='rejected'?' · 已拒绝匹配':''}${p.issues?.some(i=>['adjacent_conflict','candidate_conflict','missing_position'].includes(i))?' · 待核对':''}</span>${p.key?`<button class="button quiet" data-recall-correct="${side}">修正地点</button><button class="button quiet" data-recall-history="${side}">地点历史</button>`:'<span class="subtle">缺少可信位置</span>'}</div>${recallParkingEvidence(row,side)}`;};
  return `<div class="local-trip-intro"><h2>${recallTypes[row.type]||'行程'}${row.cross_midnight?' · 跨午夜':''}</h2><p>记录起点 ${esc(tripTime(row.start_time))}<br>${row.open?'最近观测':'记录终点'} ${esc(tripTime(row.end_time))}</p>${place('start')}${place('end')}<p>${row.type==='parking'?'停车区间跨度':'观测时长'} ${esc(tripDuration(row.duration_seconds))}${row.type==='trip'?` · 里程 ${esc(tripNumber(row.distance_km,' km'))}`:''}</p>${recallParkingDetails(row)}${row.partial&&row.type!=='parking'?'<p class="subtle">部分记录；缺失范围不推断。</p>':''}${row.reason_labels?`<p class="subtle">${row.reason_labels.map(esc).join('；')}</p>`:''}${row.type==='charge'?`<p>账单金额 ${esc(tripNumber(row.bill?.actual_cents==null?null:row.bill.actual_cents/100,' 元'))}</p><button class="button secondary" data-recall-ledger>打开账本编辑</button>`:''}<div id="recall-correction"></div><div id="recall-history"></div><button class="button secondary recall-map-jump" data-recall-map>查看地图</button></div>`;
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
  loadLocalTrips(true).then(()=>{if(localTrips===h&&showTrackPosition)loadLocalRoute();});window.scrollTo({top:0,behavior:'instant'});
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
  }).join('')}</div><p class="subtle">${m.trip_count} 趟 · ${esc(tripNumber(m.distance_km,' km'))} · ${esc(tripNumber(m.actual_cents===null?null:m.actual_cents/100,' 元'))}</p></section>`).join('')}</div><h3>常停车地点</h3><p class="subtle">按归档停车观测计数；推定地点单独标记，采样缺口不补算。</p>${(d.frequent_parking_places||[]).map(p=>`<button class="button quiet" data-recall-date="${p.date}" data-recall-record="${esc(p.record_id)}">${esc(p.label)} · ${p.count} 段${p.reference_count?' · '+p.reference_count+' 段推定地点':''}</button>`).join('')||'<p>没有可命名的停车观测。</p>'}<h3>常到达地点</h3><p class="subtle">按行程到达次数，不冒充完整停车次数。</p>${d.frequent_places.map(p=>`<p>${esc(p.label)} · ${p.arrivals} 次到达</p>`).join('')||'<p>没有可统计的地点。</p>'}`;
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
  if(target.hasAttribute('data-recall-map')){openLocalTripDetails();$('#local-trip-route').scrollIntoView({block:'start',behavior:'smooth'});return true;}
  if(target.hasAttribute('data-recall-ledger')){const row=localTrips.selected;recallLedgerReturn={date:trackDate,id:row.id,context:state?.insights_context};enterBooks('ledger',row.bill?.date||row.date,row.id);return true;}
  if(target.hasAttribute('data-recall-return')){if(recallLedgerReturn?.context===state?.insights_context)recallOpenDay(recallLedgerReturn.date,recallLedgerReturn.id);return true;}
  if(target.hasAttribute('data-recall-undo')){const h=localTrips;try{await api('/api/place-corrections',{operation:'undo',context:h.timeline.context,revision:h.timeline.correction_revision});if(h===localTrips){recallYear=null;await loadLocalTrips(true);}}catch(e){h.listError=e.message;renderLocalTripList();}return true;}
  return false;
}
document.addEventListener('click',e=>{const target=e.target.closest('[data-recall-review],[data-recall-return],[data-recall-year-load],[data-recall-date],[data-recall-correct],[data-recall-history],[data-recall-history-next],[data-recall-save],[data-recall-cancel],[data-recall-map],[data-recall-ledger],[data-recall-undo]');if(target){e.preventDefault();recallAction(target);}});
document.addEventListener('change',e=>{if(e.target.id==='recall-year-mode'&&recallYear){recallYear.mode=e.target.value;recallPaintYear();persistNavigation();}});

window.recallCanReturn=()=>recallLedgerReturn?.context===state?.insights_context;

window.recallPersonalRevision=0;
window.recallInvalidate=()=>{const reload=recallYear?.context===state?.insights_context&&$('.recall-year-panel')?.open;window.recallPersonalRevision++;recallYearSerial++;recallYear=null;recallHistory=null;if($('#recall-year-result'))$('#recall-year-result').innerHTML='<p role="status">数据已更新，请重新读取年度回顾。</p>';if(reload)recallLoadYear();};
