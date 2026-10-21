(function(root){
'use strict';
const numeric=n=>Number.isFinite(n)&&n>=0;
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const duration=seconds=>{if(!numeric(seconds))return '未知';const minutes=Math.round(seconds/60);return minutes>=60?`${Math.floor(minutes/60)} 小时${minutes%60?' '+minutes%60+' 分钟':''}`:`${minutes} 分钟`;};
const number=(value,unit='')=>numeric(value)?`${Number(value.toFixed(1))}${unit}`:'未知';
const clock=value=>numeric(value)?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(value):'未知';
const placeOf=(row,side)=>row[side+'_place']||{key:null,label:'位置未知',source:'unknown',issues:[]};
const same=(a,b)=>!!a?.key&&a.source!=='unknown'&&b?.source!=='unknown'&&a.decision!=='rejected'&&b?.decision!=='rejected'&&a.key===b?.key&&!a.issues?.length&&!b.issues?.length;
function chainModel(rows){
 const items=[];let endpoint=null,hadEvidence=false;
 for(const row of [...rows].sort((a,b)=>(a.start_time??a.end_time)-(b.start_time??b.end_time)||String(a.id).localeCompare(String(b.id)))){
  if((row.type||'trip')!=='trip'){
   items.push({kind:row.type,row});
   if(endpoint&&!same(endpoint.place,placeOf(row,'end')))endpoint=null;
   hadEvidence=row.type==='parking';continue;
  }
  const start=placeOf(row,'start'),end=placeOf(row,'end');
  if(endpoint&&same(endpoint.place,start)&&numeric(row.start_time)&&row.start_time>=endpoint.time){
   endpoint.depart_time=row.start_time;
   // Matching endpoints alone do not establish stationary time in between.
   if(!hadEvidence&&row.start_time-endpoint.time>60000)items.push({kind:'gap',start_time:endpoint.time,end_time:row.start_time});
  }else items.push({kind:'place',place:start,time:row.start_time,label:row.partial?'记录起点':'出发'});
  items.push({kind:'trip',row});
  endpoint={kind:'place',place:end,time:row.end_time,label:row.status==='driving'||row.status==='waiting'?'最近观测':row.partial?'记录终点':'到达'};
  items.push(endpoint);hadEvidence=false;
 }
 return items;
}
function daySegments(rows,date){
 const lower=Date.parse(date+'T00:00:00+08:00'),upper=lower+86400000;
 if(!Number.isFinite(lower))return [];
 return rows.filter(r=>(r.type||'trip')==='trip'&&numeric(r.start_time)&&numeric(r.end_time)&&r.end_time>r.start_time&&r.end_time>lower&&r.start_time<upper).map(row=>({row,id:row.id,start_minute:(Math.max(lower,row.start_time)-lower)/60000,end_minute:(Math.min(upper,row.end_time)-lower)/60000,clipped:row.start_time<lower||row.end_time>upper}));
}
function timeLabel(value,date){return numeric(value)?(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(value)!==date?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit'}).format(value)+' ':'')+clock(value):'未知';}
function chain(rows,selection,date){
 return chainModel(rows).map(item=>{
  if(item.kind==='place')return `<div class="tv-node"><time>${escape(timeLabel(item.time,date))}</time><i aria-hidden="true"></i><div><strong>${escape(item.place.label)}</strong><small>${escape(item.label)}${item.depart_time?' · '+escape(clock(item.depart_time))+' 再出发':''}</small></div></div>`;
  if(item.kind==='gap')return '<div class="tv-gap">间隔内移动情况未观测，未推断停车</div>';
  const r=item.row,selected=selection===r.id;
  if(item.kind==='trip')return `<div class="tv-leg ${selected?'selected':''}" data-chain-record="${escape(r.id)}"><div class="tv-rail" aria-hidden="true"></div><div><div class="tv-leg-values"><strong>${escape(number(r.distance_km,' km'))}</strong><span>行驶观测 ${escape(duration(r.duration_seconds))}</span></div><button class="local-trip-row tv-select ${selected?'selected':''}" data-local-trip="${escape(r.id)}" aria-pressed="${selected}">${selected?'已选中 · 查看详情':'查看行程'}${r.partial?' · 部分记录':''}${r.status==='driving'?' · 记录中':''}</button></div></div>`;
  const type=item.kind==='parking'?'停车观测':'充电',quality=r.observation_quality||{};
  return `<div class="tv-observation" data-chain-record="${escape(r.id)}"><button class="local-trip-row tv-select ${selected?'selected':''}" data-local-trip="${escape(r.id)}" aria-pressed="${selected}"><strong>${type}</strong> · ${escape(placeOf(r,'end').label)}${r.end_place_evidence?.source==='parking_reference'?' · 推定地点':r.end_place_evidence?.source==='parking_arrival_confirmation'?' · 人工确认到达地点':''}<span>${escape(clock(r.start_time))}—${escape(clock(r.end_time))} · ${escape(duration(r.duration_seconds))}</span>${item.kind==='parking'?`<span>${r.parking_status==='parked'?'已确认停车':'停车待确认'}${numeric(quality.unknown_seconds)&&quality.unknown_seconds>0?' · 缺口 '+escape(duration(quality.unknown_seconds)):''}${r.open?' · 后续未观测':''}</span>`:r.partial?'<span>部分记录</span>':''}</button></div>`;
 }).join('');
}
function clockChart(rows,date,selection){
 const segments=daySegments(rows,date),r=78,cx=130,cy=120;
 const point=minute=>{const angle=minute/1440*Math.PI*2-Math.PI/2;return [cx+r*Math.cos(angle),cy+r*Math.sin(angle)];};
 const path=(a,b)=>{const start=point(a),end=point(b);return `M${start.join(',')} A${r},${r} 0 ${b-a>720?1:0} 1 ${end.join(',')}`;};
 const arcs=segments.flatMap(s=>s.end_minute-s.start_minute>=1440?[{...s,end_minute:720},{...s,start_minute:720}]:[s]);
 const merged=[];for(const s of [...segments].sort((a,b)=>a.start_minute-b.start_minute)){const last=merged.at(-1);if(last&&s.start_minute<=last[1])last[1]=Math.max(last[1],s.end_minute);else merged.push([s.start_minute,s.end_minute]);}
 const minutes=merged.reduce((n,[a,b])=>n+b-a,0);
 return `<svg viewBox="0 0 260 245" class="tv-clock" role="img" aria-label="24小时时钟，显示${escape(date)}内已记录的行驶时段"><circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--tv-track)" stroke-width="13"/>${[0,6,12,18].map(h=>{const angle=h/24*Math.PI*2-Math.PI/2;return `<text x="${cx+(r+22)*Math.cos(angle)}" y="${cy+(r+22)*Math.sin(angle)+4}" text-anchor="middle">${String(h).padStart(2,'0')}</text>`;}).join('')}${arcs.map(s=>`<g data-local-select="${escape(s.id)}" class="tv-clock-hit"><path d="${path(s.start_minute,s.end_minute)}" fill="none" stroke="transparent" stroke-width="29"/><path d="${path(s.start_minute,s.end_minute)}" fill="none" stroke="var(--accent)" stroke-width="${selection===s.id?17:13}" ${s.row.partial?'stroke-dasharray="3 2"':''}/></g>`).join('')}<text x="${cx}" y="${cy-20}" text-anchor="middle">当天行驶时段</text><text class="tv-clock-value" x="${cx}" y="${cy+7}" text-anchor="middle">${segments.length?escape(duration(minutes*60)):'暂无记录'}</text><text x="${cx}" y="${cy+31}" text-anchor="middle">${segments.length} 段已记录时段</text></svg><div id="local-trip-clock-rows" class="tv-clock-rows">${segments.map(s=>`<button class="button quiet" data-local-select="${escape(s.id)}" aria-pressed="${selection===s.id}"><span>${escape(timeLabel(s.row.start_time,date))}—${escape(timeLabel(s.row.end_time,date))}</span><span>${escape(duration((s.end_minute-s.start_minute)*60))}${s.clipped?' · 当天片段':''}</span></button>`).join('')}</div>`;
}
function summary(timeline,date){
 if(!timeline)return '';
 const s=timeline.summary||{},c=timeline.coverage||{},charges=numeric(s.actual_cents)?`${Number((s.actual_cents/100).toFixed(2))} 元`:'未知';
 return `<div class="tv-summary"><div><h2>${escape(date)}</h2><small>当天出行 · 北京时间</small></div><div><small>结束行程里程</small><strong>${escape(number(s.distance_km))}</strong> km</div><div><small>观测驾驶时长</small><strong>${escape(duration(s.duration_seconds))}</strong></div><div><small>结束行程</small><strong>${s.trip_count??0}</strong> 趟</div></div><div class="tv-bills">充电 ${s.charge_count??0} 次 · 已填账单 ${escape(charges)} · 待补账 ${s.pending_count??0} 次</div><p class="section-note">${{missing:'无归档观测；不代表当天没用车。',limited:'观测受限。',observed:'有有效车辆时刻，不表示全天覆盖。',future:'未来日期。'}[c.coverage]||'覆盖未知。'}跨日里程归结束日；时钟仅显示当天时段。</p>`;
}
function overview(data,date){
 if(!data)return '';
 const days=data.days||[],max=Math.max(1,...days.map(d=>d.distance_km||0));
 const related=dates=>dates.map(d=>`<button class="button quiet" data-recall-date="${escape(d)}">${escape(d)}</button>`).join('');
 const route=r=>`<details class="tv-rank"><summary><span>${escape(r.label)}</span><b>${r.count} 趟</b><div class="tv-meter"><i style="width:${r.count/Math.max(1,data.routes[0]?.count||1)*100}%"></i></div><small>单程约 ${escape(number(r.median_distance_km,' km'))} · ${r.count>1?'典型':'本次'} ${escape(duration(r.median_duration_seconds))}</small></summary><div class="tv-related">${related(r.dates)}</div></details>`;
 return `<section class="card tv-week-trend"><div class="card-head"><h3>近 7 天里程</h3><span class="subtle">${escape(number(data.distance_km,' km'))} · ${data.trip_count} 趟</span></div><div class="tv-trend" data-trip-trend></div><div class="tv-week-days">${days.map(d=>`<button class="button quiet ${d.date===date?'selected':''}" data-recall-date="${escape(d.date)}" aria-pressed="${d.date===date}"><span>${escape(d.date.slice(5))}</span><small>${d.distance_km===null?'无里程记录':escape(number(d.distance_km,' km'))}${d.missing_distance_count?' · 部分里程未知':''}</small></button>`).join('')}</div></section><div class="tv-analysis-grid"><section class="card"><div class="card-head"><h3>常走路线</h3><span class="subtle">往返合并 · 按单程计趟</span></div><div class="tv-ranks">${data.routes.length?data.routes.slice(0,3).map(route).join(''):'<p class="subtle">暂无可定位的路线。</p>'}${data.routes.length>3?`<details><summary>其他 ${data.routes.length-3} 条路线</summary>${data.routes.slice(3).map(route).join('')}</details>`:''}${data.unknown_route_count?`<p class="subtle">${data.unknown_route_count} 趟端点未确认，未归入路线。</p>`:''}<p class="subtle">典型用时取单程中位数</p></div></section><section class="card"><div class="card-head"><h3>常去地点</h3><span class="subtle">到达次数 · 已观测停车</span></div><div class="tv-ranks">${data.places.length?data.places.map(p=>`<details class="tv-rank"><summary><span>${escape(p.label)}</span><b>${p.arrivals} 次</b><div class="tv-meter"><i style="width:${p.arrivals/Math.max(1,data.places[0]?.arrivals||1)*100}%"></i></div><small>已观测停车 ${escape(duration(p.observed_parking_seconds))}${p.parking_incomplete?' · 有缺口或待确认':''}</small></summary><div class="tv-related">${related(p.dates)}</div></details>`).join(''):'<p class="subtle">暂无可定位的到访与停车记录。</p>'}${data.unknown_arrivals?`<p class="subtle">${data.unknown_arrivals} 次到达地点未知，未归入地点。</p>`:''}</div></section></div>`;
}
function drawTrend(target,data,date){
 if(!target||!data)return;
 const width=target.clientWidth;if(width<200)return;
 const height=170,left=40,right=22,top=28,bottom=32,max=Math.max(1,Math.ceil(Math.max(0,...data.days.map(d=>d.distance_km||0))/20)*20);
 const x=i=>left+i*(width-left-right)/Math.max(1,data.days.length-1),y=n=>height-bottom-n/max*(height-top-bottom);
 let path='',continuing=false;
 data.days.forEach((d,i)=>{if(!numeric(d.distance_km)){continuing=false;return;}path+=(continuing?' L':' M')+x(i)+','+y(d.distance_km);continuing=true;});
 target.innerHTML=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="近7天已记录里程，缺少记录的日期留空"><text x="1" y="15">km</text>${[0,max/2,max].map(n=>`<line x1="${left}" y1="${y(n)}" x2="${width-right}" y2="${y(n)}" stroke="var(--line)"/><text x="${left-8}" y="${y(n)+4}" text-anchor="end">${Number(n.toFixed(1))}</text>`).join('')}<path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"/>${data.days.map((d,i)=>`<g>${numeric(d.distance_km)?`<circle cx="${x(i)}" cy="${y(d.distance_km)}" r="${d.date===date?5:3}" fill="var(--accent)"/><text class="tv-value-label" x="${x(i)+(i===0?7:0)}" y="${y(d.distance_km)-12}" text-anchor="${i===0?'start':i===data.days.length-1?'end':'middle'}">${number(d.distance_km)}</text>`:''}<text x="${x(i)}" y="${height-10}" text-anchor="middle">${escape(d.date.slice(5))}</text></g>`).join('')}</svg>`;
}
const API={chainModel,daySegments,duration,chain,clockChart,summary,overview,drawTrend};
if(typeof module==='object'&&module.exports)module.exports=API;else root.LocalTripVisuals=API;
})(typeof window==='undefined'?globalThis:window);
