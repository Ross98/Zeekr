'use strict';

const icons = {
  overview: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  car: '<path d="m4 10 2-6h12l2 6M4 10h16v8H4zM2 10h20M7 18v2m10-2v2M7 13h1m8 0h1"/>',
  energy: '<path d="m13 2-8 12h6l-1 8 9-13h-7z"/>',
  map: '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2.5"/>',
  tracks: '<circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M5 7v6a3 3 0 0 0 3 3h2a3 3 0 0 0 0-6h4a5 5 0 0 1 5 5v2"/>',
  fields: '<path d="M8 4h12M8 12h12M8 20h12"/><circle cx="3" cy="4" r=".5"/><circle cx="3" cy="12" r=".5"/><circle cx="3" cy="20" r=".5"/>',
  settings: '<path d="m9 3-1 3-3 1v4l-2 1 2 2v3l3 1 1 3h5l1-3 3-1v-3l3-2-3-2V7l-3-1-1-3z"/><circle cx="11.5" cy="12" r="3"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"/>',
  arrow: '<path d="m9 5 7 7-7 7"/>',
  battery: '<rect x="2" y="6" width="18" height="12" rx="2"/><path d="M22 10v4M5 9v6m4-6v6m4-6v6"/>',
  range: '<path d="m8 3-5 18m13-18 5 18M12 3v4m0 4v3m0 4v3"/>',
  odometer: '<path d="M4 19a10 10 0 1 1 16 0Z"/><path d="m12 13 5-5"/><circle cx="12" cy="13" r="1"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.2"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'
};
const pages = { overview: '总览', car: '车辆', energy: '能源与充电', map: '定位地图', tracks: '行程与轨迹', fields: '参数字典', insights: '用车研究', settings: '设置', more: '更多' };
const descriptions = { overview: '', car: '完整参数与状态总览，保留原值、解释依据和来源时间。', energy: '查看当前观测状态、充电记录与计算依据。', map: '最近返回的位置，保留可信度与时间信息。', tracks: '留住走过的路，也如实保留数据的空白。', fields: '查看中文解释、原始字段与验证状态。', insights: '从历史观测，看懂每一次变化。', settings: '管理本机连接、隐私与轨迹采集。', more: '更多车辆信息与本机设置。' };
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.info}</svg>`;
let state = null, page = 'overview', busy = false, transientError = '', showPosition = false, showCoordinates = false;
let map = null, mapMarker = null, generation = 0, toastTimer;
let trackSource = 'local', trackDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year:'numeric',month:'2-digit',day:'2-digit' }).format(new Date());
let trackData = null, playback = [], search = '', groupFilter = '', unknownOnly = false;
const beijingDate = value => new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
let chargeDate = beijingDate(Date.now()), chargeDateInitialized = false;
let chargeEvents = [], chargeSelected = null, chargeCursor = null, chargeCursorStack = [], chargeNextCursor = null, chargeBusy = false, chargeError = '', chargeRequest = 0;
let chargingTab = 'process', chargingView = 'power-soc', chargingDays = 30, chargingMode = 'all';
let chargingSelection = 'current';
let chargingSession = null, chargingSeries = null, chargingStats = null, chargingAnalyticsError = '', chargingAnalyticsBusy = false, chargingAnalyticsRequest = 0, chargingPoint = 0;
let chargingAnalyticsLoadedKey = '', chargingAnalyticsLoadingKey = '';
let connectionFailures = 0, polling = false;
let refreshMessage = '';
let samplingDraft = null;
const refreshMessages = {cached:'已复用本机缓存，未请求云端。',unchanged:'已读取云端，车辆数据未更新。',new:'已获得新车辆数据。',time_unknown:'已读取云端，车辆更新时间未知。'};

const vehiclePage = window.VehiclePage.create({getState:()=>state,request:api,redraw:render,escape:esc,age,active:()=>page==='car'});

const insightsPage = window.InsightsPage.create({getState:()=>state,request:api,escape:esc,active:()=>page==='insights',review:openResearchReview});
const tripManager = window.TripManagement.create({getState:()=>state,getDate:()=>trackDate,request:api,escape:esc,
  active:()=>page==='tracks'&&trackSource==='local'&&tripManagementOpen,
  changed:revision=>{
    state.trip_records_revision=revision;
    if(localTrips){clearLocalRoute();localTrips.selection='day';localTrips.selected=null;localTrips.events=null;
      localTrips.cursor=null;localTrips.previous=[];localTrips.listRequest++;localTrips.listTask=null;
      renderLocalTripDetail();loadLocalTrips();}
    pollState(true);
  }});

function navigation() {
  $('#navigation').innerHTML = Object.entries(pages).filter(([key]) => key !== 'more').map(([key, label]) => `<button class="nav-item ${page === key ? 'active' : ''}" data-page="${key}" ${page === key ? 'aria-current="page"' : ''}>${icon(key)}${label}</button>`).join('');
  $('#mobile-navigation').innerHTML = ['overview','car','map','tracks','more'].map(key => `<button data-page="${key}" class="${page === key || (key === 'more' && ['energy','fields','insights','settings'].includes(page)) ? 'active' : ''}" aria-label="${pages[key]}">${icon(key)}<span>${{overview:'总览',car:'车辆',map:'地图',tracks:'轨迹',more:'更多'}[key]}</span></button>`).join('');
}

async function api(path, data, timeout = 50000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const options = data === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-Request-Key':state?.request_key || ''},body:JSON.stringify(data)};
    const response = await fetch(path, {...options,signal:controller.signal});
    if (response.status === 401) { location.replace("/"); throw new Error("请重新登录。"); }
    let value;
    try { value = await response.json(); } catch { throw Error('本机服务响应无效，请重试。'); }
    if (!response.ok) throw Error(value.error || '请求失败，请稍后重试。');
    return value;
  } catch(error) {
    if(error.name==='AbortError') throw Error('本机服务响应超时，请稍后重试。');
    throw error;
  } finally { clearTimeout(timer); }
}

function relativeTime(value) {
  if (!Number.isFinite(value)) return '更新时间未知';
  const seconds = Math.floor((Date.now()-value)/1000);
  if(seconds < -60) return '时间异常，请核对时钟';
  if(seconds < 60) return '不足 1 分钟前';
  if(seconds < 3600) return `${Math.floor(seconds/60)} 分钟前`;
  if(seconds < 86400) return `${Math.floor(seconds/3600)} 小时 ${Math.floor(seconds%3600/60)} 分钟前`;
  return `${Math.floor(seconds/86400)} 天前`;
}
function age(value, prefix = '') {
  return `<span data-age="${Number.isFinite(value)?value:''}" data-prefix="${esc(prefix)}">${esc(prefix+relativeTime(value))}</span>`;
}
function waitSeconds() { return Math.max(0,Math.ceil((state?.next_query_at || 0)-Date.now()/1000)); }
function updateClock() {
  document.querySelectorAll('[data-age]').forEach(el => {
    const value=el.dataset.age===''?null:Number(el.dataset.age);
    el.textContent=el.dataset.prefix+relativeTime(value);
  });
  const button = document.querySelector('[data-action="refresh"]');
  const remaining=waitSeconds();
  if(button) {
    button.disabled=busy || remaining>0;
    button.innerHTML=`${icon('refresh')}${busy?'读取中…':remaining?`等待 ${remaining} 秒`:'刷新状态'}`;
  }
  if($('#refresh-hint')) $('#refresh-hint').textContent=remaining?`${remaining} 秒后可再次请求云端`:'读取云端缓存，车辆可能尚未更新';
}
function updateConnection() {
  const disconnected=connectionFailures>=2;
  $('#connectivity-notice').hidden=!disconnected;
  $('#local-connection').textContent=disconnected?'本机服务已断开':connectionFailures?'正在重连…':'本机服务已连接';
  $('#connection').textContent=disconnected?'本机服务已断开':state?.error?'车辆读取需检查':state?.authenticated?'本机会话已保存':'尚未登录';
  $('#local-connection').classList.toggle('unknown',disconnected);
}

function toast(message) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500);
}

function pill(value, kind = '', symbol = '') { return `<span class="pill ${kind}">${symbol ? icon(symbol) : ''}${esc(value)}</span>`; }
function row(name, value) { return `<div class="inline-row"><span>${esc(name)}</span><strong>${esc(value)}</strong></div>`; }
function action(label, name, kind = '', symbol = '') { return `<button class="button ${kind}" data-action="${name}" ${busy ? 'disabled' : ''}>${symbol ? icon(symbol) : ''}${esc(label)}</button>`; }
function link(label, target) { return `<button class="text-link" data-page="${target}">${esc(label)}${icon('arrow')}</button>`; }
function empty(title, text, symbol = 'info') { return `<div class="empty">${icon(symbol)}<h2>${esc(title)}</h2><p>${esc(text)}</p></div>`; }
function head() {
  return `<div class="page-head"><div><div class="eyebrow">MY ZEEKR / ${new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit'}).format(new Date())}</div><h1>${pages[page]}</h1><div class="subtle">${descriptions[page]}</div></div><div class="page-actions">${page!=='tracks' && state?.vehicles?.length > 1 ? `<select id="vehicle-select" class="select" aria-label="选择车辆" >${state.vehicles.map(v => `<option value="${v.number}" ${v.number === state.vehicle ? 'selected' : ''}>${esc(v.label)}</option>`).join('')}</select>` : ''}<div class="refresh-control">${action(busy ? '读取中…' : '刷新状态','refresh','','refresh')}<span id="refresh-hint" class="subtle"></span></div></div></div>`;
}

function modelRequired() {
  if (state?.model) return '';
  const logged = state?.authenticated;
  return `<div class="card">${empty(logged ? '尚未读取车辆状态' : '连接你的极氪', logged ? '本机会话已就绪。点击“刷新状态”，读取车辆云端缓存。' : '先在本机终端完成登录，再返回页面刷新。手机号、验证码与凭据不进入页面。', 'car')}${!logged ? '<div class="empty" style="padding-top:0"><code>python3 -m zeekr_control login</code></div>' : ''}</div>`;
}

function metric(label, value, symbol, foot, battery = false) {
  if (value && typeof value==='object') {
    value=Number.isFinite(value.value)?`${new Intl.NumberFormat('zh-CN',{maximumFractionDigits:3}).format(value.value)}${value.unit==='%'?'%':` ${value.unit}`}`:'未知';
  }
  const parts = value.match(/^(.*?)(%| km)$/);
  const num = parts ? parts[1] : value;
  const unit = parts ? parts[2].trim() : '';
  const percent = battery && value.endsWith('%') ? Math.max(0, Math.min(100, parseFloat(value))) : 0;
  return `<div class="metric"><div class="metric-label">${icon(symbol)}${label}</div><div class="metric-value">${esc(num)}${unit ? `<span class="metric-unit">${unit}</span>` : ''}</div>${battery && value.endsWith('%') ? `<div class="battery-track"><div class="battery-fill" style="width:${percent}%"></div></div>` : ''}<div class="metric-foot">${esc(foot)}</div></div>`;
}

function tyres(compact = false) {
  return `<div class="tyre-grid">${state.model.tyres.map(t => `<div class="tyre-item"><span class="tyre-name">${esc(t.name)}</span><div><span class="tyre-value">${esc(compact && Number.isFinite(t.pressure_value)?`${t.pressure_value.toFixed(1)} kPa`:t.pressure)}</span><span class="tyre-temp">${esc(t.temperature)}</span></div></div>`).join('')}</div>`;
}

function eventSummary(event, kind) {
  if (!event) return `<p class="subtle">暂无已完成记录。</p>`;
  const format = value => Number.isFinite(value) ? new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1}).format(value) : '未知';
  const complete = event.partial ? '部分记录' : '完整记录';
  if (kind === 'trip_end') return `<div class="event-summary"><strong>${format(event.distance_km)} km</strong><span>${format(event.start_soc)}% 至 ${format(event.end_soc)}%</span><small>${complete} · ${esc(new Date(event.end_time).toLocaleString('zh-CN',{hour12:false}))}</small></div>`;
  const capacity = Number.isFinite(event.battery_capacity_kwh) && Number.isFinite(event.soc_delta) && event.soc_delta > 0
    ? `${format(event.battery_capacity_kwh * event.soc_delta / 100)} kWh（估算）` : '充入电量无法估算';
  return `<div class="event-summary"><strong>${format(event.start_soc)}% 至 ${format(event.end_soc)}%</strong><span>${capacity}</span><small>${complete} · ${esc(new Date(event.end_time).toLocaleString('zh-CN',{hour12:false}))}</small></div>`;
}

function eventTime(value) {
  if (!Number.isFinite(value)) return '未知';
  return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)).replaceAll('/','-');
}

function eventDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '未知';
  const minutes=Math.round(seconds/60), hours=Math.floor(minutes/60), rest=minutes%60;
  if (hours && rest) return `${hours} 小时 ${rest} 分钟`;
  if (hours) return `${hours} 小时`;
  return `${minutes} 分钟`;
}

function chargeNumber(value, unit='') {
  return Number.isFinite(value)?`${new Intl.NumberFormat('zh-CN',{maximumFractionDigits:3}).format(value)}${unit?' '+unit:''}`:'未提供 / 未记录';
}
const chargingFormat = value => Number.isFinite(value) ? new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1}).format(value) : '未知';

function chargingParameterGroups(start, end=null) {
  const rows=start?.parameters || end?.parameters || [];
  const endRows=new Map((end?.parameters || []).map(item=>[item.key,item]));
  const display=item=>`${chargeNumber(item?.value,item?.unit)}${item?.note?' · '+item.note:''}`;
  return [...new Set(rows.map(item=>item.group))].map(group=>`<section class="charging-parameter-group"><h3>${esc(group)}</h3><div class="charging-parameter-grid">${rows.filter(item=>item.group===group).map(item=>`<div class="charging-parameter"><span>${esc(item.label)}</span>${end?`<small>起点：${esc(display(item))}</small><small>终点：${esc(display(endRows.get(item.key)))}</small>`:`<strong>${esc(chargeNumber(item.value,item.unit))}</strong>${item.note?`<small>${esc(item.note)}</small>`:''}`}</div>`).join('')}</div></section>`).join('');
}

function startEvidenceView(value) {
  const stamp = time => Number.isFinite(time) && time > 0 && time <= 32503680000000;
  const clock = time => stamp(time) ? new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(time) : '未知';
  const known = value && ['bounded','first_observation'].includes(value.basis) && stamp(value.first_state_time) && stamp(value.detected_at);
  if (!known) return '<div class="start-evidence"><strong>起点证据：历史证据缺失</strong><p>实际开始时间未知；原记录起点保留，无法据此补算真实开始。</p></div>';
  const bounded = value.basis === 'bounded' && stamp(value.earliest_time) && stamp(value.latest_time) && value.earliest_time < value.latest_time;
  const seconds = v => Number.isFinite(v) && v >= 0 ? new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1}).format(v) + ' 秒' : '未知';
  const delay = Number.isFinite(value.delay_min_seconds) && value.delay_min_seconds >= 0
    ? bounded && Number.isFinite(value.delay_max_seconds) ? `${seconds(value.delay_min_seconds)} ～ ${seconds(value.delay_max_seconds)}` : `至少 ${seconds(value.delay_min_seconds)}，上限未知` : '时钟差异，待核验';
  return `<div class="start-evidence"><strong>起点证据：${bounded?'相邻观测圈定范围':'首次看到时已开始'}</strong>${bounded?`<p>可能开始范围：${esc(clock(value.earliest_time))} ～ ${esc(clock(value.latest_time))}</p>`:'<p>实际开始时间未知，开头可能缺失。</p>'}${row('首次活动样本',clock(value.first_state_time))}${row('系统首次发现',clock(value.detected_at))}${row('首次样本年龄',seconds(value.sample_age_seconds))}${row('发现延迟范围',delay)}<p>尚无精确开始事件。样本年龄不等于真实开始延迟；里程、电量按原采样点统计。</p></div>`;
}

function chargingUnavailable() {
  return `<p class="energy-caption">充电限值、停止原因、电池包温度、桩端结算电量与费用、预约时段：接口未提供或未核验。充电枪连接码不单独推断插拔；高压温度等级不是电池温度。</p>`;
}

function chargingCurrent(details) {
  return `<section class="card" id="charging-parameters"><div class="card-head"><div><h2>充电状态参数</h2><p class="card-meta">当前缓存观测 · ${esc(eventTime(details?.state_time))}</p></div>${pill('只读')}</div><div class="card-body"><div class="charging-power">${row('当前观测功率',chargeNumber(details?.power_kw,'kW'))}<p class="energy-caption">${details?.power_source==='ac_ui'?'交流充电电压 × 电流':details?.power_source==='dc_pile_ui'?'直流桩侧电压 × 电流':'缺少可确认的充电与电气证据，暂不计算功率'}；同一观测计算值，不是实时保证或桩端结算值。</p></div>${chargingParameterGroups(details)}${chargingUnavailable()}</div></section>`;
}

function chartGeometry(points, key, options={}) {
  const valid=points.filter(point=>Number.isFinite(point.time)&&Number.isFinite(point[key]));
  if(!valid.length) return null;
  const times=valid.map(point=>point.time), values=valid.map(point=>point[key]);
  const minX=Math.min(...times), maxX=Math.max(...times);
  let minY=Number.isFinite(options.minY)?options.minY:Math.min(...values);
  let maxY=Number.isFinite(options.maxY)?options.maxY:Math.max(...values);
  if(minY===maxY) {
    const pad=Math.max(1,Math.abs(minY)*.05);
    if(Number.isFinite(options.minY)) maxY+=pad;
    else if(Number.isFinite(options.maxY)) minY-=pad;
    else {minY-=pad;maxY+=pad;}
  }
  const x=time=>minX===maxX?400:64+(time-minX)/(maxX-minX)*672;
  const y=value=>180-(value-minY)/(maxY-minY)*156;
  let previous=null,lastDot=null;
  const dots=[],commands=[],gaps=[];
  points.forEach((point,index)=>{
    if(!Number.isFinite(point.time)||!Number.isFinite(point[key])) { previous=null;return; }
    const px=x(point.time),py=y(point[key]);
    const connected=previous&&previous.segment_id===point.segment_id;
    if(connected&&options.step) commands.push(`H${px.toFixed(1)} V${py.toFixed(1)}`);
    else commands.push(`${connected?'L':'M'}${px.toFixed(1)},${py.toFixed(1)}`);
    if(!connected&&lastDot) gaps.push({x:(lastDot.x+px)/2});
    const dot={x:px,y:py,index,time:point.time,segment_id:point.segment_id};
    dots.push(dot);lastDot=dot;previous=point;
  });
  return {path:commands.join(' '),dots,gaps,minX,maxX,minY,maxY,x,y};
}

function chargingChart(title, key, unit) {
  const points=chargingSeries?.points || [];
  const values=points.map(point=>point[key]).filter(Number.isFinite);
  const options=key==='soc'?{minY:0,maxY:100,step:true}:key==='power_kw'?{minY:0,maxY:Math.max(1,...values)*1.1}:{};
  const chart=chartGeometry(points,key,options);
  if(!chart) return `<section class="charging-chart"><h3>${esc(title)}</h3><div class="chart-empty">该记录未保存有效过程采样</div></section>`;
  const ticks=[chart.maxY,(chart.minY+chart.maxY)/2,chart.minY];
  const number=value=>Number(value.toPrecision(4)).toString();
  const time=value=>new Date(value).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const labels=ticks.map(value=>`<text class="chart-axis" x="56" y="${chart.y(value)+5}" text-anchor="end">${esc(number(value))}</text>`).join('');
  const dots=chart.dots.map(point=>`<circle class="chart-point${point.index===chargingPoint?' selected':''}" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="${point.index===chargingPoint?'5':'2.5'}"/>`).join('');
  const selected=points[chargingPoint], cursor=Number.isFinite(selected?.time)?chart.x(selected.time):null;
  const cursorLine=Number.isFinite(cursor)?`<line class="chart-cursor" x1="${cursor.toFixed(1)}" y1="24" x2="${cursor.toFixed(1)}" y2="180"/>`:'';
  const gaps=chart.gaps.map(gap=>`<line class="chart-gap" x1="${gap.x.toFixed(1)}" y1="24" x2="${gap.x.toFixed(1)}" y2="180"><title>观测缺口</title></line>`).join('');
  const gapLabel=chart.gaps.length?` · ${chart.gaps.length} 处缺口`:'';
  return `<section class="charging-chart"><div class="charging-chart-head"><h3>${esc(title)}</h3><span>${chart.dots.length} 个有效点${gapLabel} · ${esc(unit)}</span></div><div class="charging-chart-scroll" tabindex="0" role="region" aria-label="${esc(title)}图表，可横向滚动"><svg viewBox="0 0 760 225" role="img" aria-label="${esc(title)}折线图，单位 ${esc(unit)}，横轴为北京时间；缺失采样不连线"><path class="chart-grid" d="M64 24H736M64 102H736M64 180H736"/>${labels}<text class="chart-axis" x="64" y="216">${esc(time(chart.minX))}</text><text class="chart-axis" x="736" y="216" text-anchor="end">${esc(time(chart.maxX))} 北京时间</text>${gaps}${cursorLine}<path class="chart-line" d="${chart.path}"/>${dots}</svg></div></section>`;
}

function selectedChargingPoint() {
  const points=chargingSeries?.points || [];
  return points[Math.min(chargingPoint,Math.max(0,points.length-1))] || null;
}

function chargeHistoryPanel() {
  return `<section class="charge-history-section" id="charge-history"><div class="charge-history-head"><div><h2>充电记录</h2><p>按结束时间归入北京时间日期，每页显示 20 条。</p></div><label>充电记录日期<input type="date" id="charge-date" value="${esc(chargeDate)}"></label></div><div class="charge-history-layout"><section class="card charge-list-card"><div id="charge-list">${chargeHistoryBody()}</div></section>${chargeDetail(chargeSelected)}</div></section>`;
}

function chargingProcess() {
  if(chargingAnalyticsBusy&&!chargingSession) return `<div class="charge-loading" role="status">正在读取充电过程…</div>`;
  if(chargingAnalyticsError) return `${empty('充电过程读取失败',chargingAnalyticsError,'energy')}<div class="charge-empty-action"><button class="button secondary" data-action="analytics-retry">重试</button></div>`;
  if(!chargingSession||chargingSession.status==='empty') return `${empty('暂无进行中的充电过程','已结束记录仍可从下方充电记录中选择；没有过程采样时保留事件摘要。','energy')}${chargeHistoryPanel()}`;
  const historical=chargingSession.status==='ended', point=selectedChargingPoint(), points=chargingSeries?.points || [];
  const summary=`<div class="charging-process-summary"><div><span>${historical?'历史起点':'本次起点'}</span><strong>${Number.isFinite(chargingSession.start_soc)?chargingFormat(chargingSession.start_soc)+'%':'未知'}</strong></div><div><span>${historical?'历史终点':'当前 SOC'}</span><strong>${Number.isFinite(chargingSession.end_soc)?chargingFormat(chargingSession.end_soc)+'%':'未知'}</strong></div><div><span>观测功率</span><strong>${chargeNumber(chargingSession.power_kw,'kW')}</strong></div><div><span>采样覆盖</span><strong>${chargingSeries?.raw_count||0} 点${chargingSeries?.has_gaps?' · 有缺口':''}</strong></div></div>`;
  const selector=points.length?`<label class="charging-point-picker">时间选择器<input id="charging-point" type="range" min="0" max="${points.length-1}" value="${Math.min(chargingPoint,points.length-1)}"><span>${point?eventTime(point.time):'未知'} · SOC ${chargeNumber(point?.soc,'%')} · ${chargingView==='power-soc'?`功率 ${chargeNumber(point?.power_kw,'kW')}`:`电压 ${chargeNumber(point?.voltage,'V')} / 电流 ${chargeNumber(point?.current,'A')}`}</span></label>`:'';
  return `<div class="charging-process-title">${historical?pill('历史详情','warn'):pill('本次观测','good')}<span>${esc(eventTime(chargingSession.start_time))} 至 ${esc(eventTime(chargingSession.end_time))}</span></div>${summary}${startEvidenceView(chargingSession.start_evidence)}<div class="charging-view-switch"><button data-action="charging-view" data-view="power-soc" class="${chargingView==='power-soc'?'active':''}">功率与 SOC</button><button data-action="charging-view" data-view="electrical" class="${chargingView==='electrical'?'active':''}">电气细节</button></div><div class="charging-charts">${chargingView==='power-soc'?chargingChart('观测功率','power_kw','kW')+chargingChart('动力电池 SOC','soc','%'):chargingChart('电压','voltage','V')+chargingChart('电流','current','A')}</div>${selector}<p class="energy-caption">同一车辆状态时间轴；缺口断线，缺值不补零。停止只表示已观测停止，不解释为充满、达到目标或已拔枪。</p>${chargeHistoryPanel()}`;
}

function chargingStatistics() {
  if(chargingAnalyticsBusy&&!chargingStats) return `<div class="charge-loading" role="status">正在计算充电统计…</div>`;
  if(chargingAnalyticsError) return empty('充电统计读取失败',chargingAnalyticsError,'energy');
  const stats=chargingStats;
  if(!stats) return empty('暂无统计数据','本地统计尚未读取。','energy');
  const s=stats.summary, max=Math.max(1,...stats.daily.map(day=>day.ac_kwh+day.dc_kwh+day.unknown_kwh));
  const bars=stats.daily.map(day=>{const total=day.ac_kwh+day.dc_kwh+day.unknown_kwh;return `<div class="charging-day" title="${esc(day.date)} · ${chargingFormat(total)} kWh"><div class="charging-bar"><i class="ac" style="height:${day.ac_kwh/max*100}%"></i><i class="dc" style="height:${day.dc_kwh/max*100}%"></i><i class="unknown" style="height:${day.unknown_kwh/max*100}%"></i></div><span>${day.date.slice(5)}</span></div>`}).join('');
  const records=stats.records.length?stats.records.map(record=>`<button class="charging-stat-record" data-action="stats-detail" data-event-id="${esc(record.id)}"><span>${esc(eventTime(record.end_time))}</span><b>${record.mode==='ac'?'AC':record.mode==='dc'?'DC':'未知'} · ${chargeNumber(record.start_soc,'%')} → ${chargeNumber(record.end_soc,'%')}</b><small>${record.partial?'部分记录':eventDuration(record.duration_seconds)} · ${Number.isFinite(record.estimated_kwh)?chargingFormat(record.estimated_kwh)+' kWh（估算）':'不计入完整电量'}</small></button>`).join(''):`<div class="chart-empty">所选范围没有已记录事件；不代表车辆没有充电。</div>`;
  const current=stats.current?`<div class="notice info">${icon('energy')}进行中会话：${stats.current.mode==='ac'?'AC':stats.current.mode==='dc'?'DC':'模式未知'} · ${chargeNumber(stats.current.start_soc,'%')} → ${chargeNumber(stats.current.end_soc,'%')}。单列展示，不计入已结束次数。</div>`:'';
  return `<div class="charging-stat-controls"><div><button data-action="stats-days" data-days="7" class="${chargingDays===7?'active':''}">最近 7 天</button><button data-action="stats-days" data-days="30" class="${chargingDays===30?'active':''}">最近 30 天</button></div><label>模式筛选<select id="charging-mode"><option value="all" ${chargingMode==='all'?'selected':''}>全部</option><option value="ac" ${chargingMode==='ac'?'selected':''}>AC</option><option value="dc" ${chargingMode==='dc'?'selected':''}>DC</option></select></label></div>${current}<div class="charging-stat-summary"><div><span>已结束次数</span><strong>${s.ended_count}</strong><small>完整 ${s.complete_count} · 部分 ${s.partial_count}</small></div><div><span>估算充入电量</span><strong>${chargingFormat(s.estimated_kwh)}<small> kWh</small></strong><small>纳入 ${s.included_energy_count} · 排除 ${s.excluded_energy_count}</small></div><div><span>完整记录时长</span><strong>${eventDuration(s.complete_duration_seconds)}</strong><small>不是插枪总时长</small></div></div><section class="card charging-daily"><div class="card-head"><h2>每日估算充入电量</h2><span class="charging-legend"><span><i aria-hidden="true"></i>AC</span><span><i class="dc" aria-hidden="true"></i>DC</span><span><i class="unknown" aria-hidden="true"></i>未知</span></span></div><div class="charging-bars">${bars}</div><p class="energy-caption">按充电结束日归档；空位只表示无已记录事件。部分记录不进入电量与完整时长。</p></section><section class="card"><div class="card-head"><h2>单次记录</h2>${pill(`${stats.records.length} 条`)}</div><div class="charging-stat-records">${records}</div></section>`;
}

function chargingWorkspace(details) {
  const tabs=[['process','本次过程'],['statistics','统计趋势'],['parameters','参数详情']];
  const body=chargingTab==='process'?chargingProcess():chargingTab==='statistics'?chargingStatistics():chargingCurrent(details);
  return `<section class="charging-workspace"><div class="charging-tabs" role="tablist">${tabs.map(([key,label])=>`<button role="tab" aria-selected="${chargingTab===key}" data-action="charging-tab" data-tab="${key}" class="${chargingTab===key?'active':''}">${label}</button>`).join('')}</div><div class="charging-tab-panel">${body}</div></section>`;
}

function chargingAnalyticsKey(selected='current') {
  const vehicle=state?.vehicle || '';
  if(chargingTab==='statistics') return `${vehicle}|statistics|${chargingDays}|${chargingMode}|${state?.recent_events?.charge_end?.id||state?.recent_events?.charge_end?.end_time||''}`;
  const revision=selected==='current'?(state?.snapshot_revision||state?.model?.updated_time||''):'';
  return `${vehicle}|process|${selected}|${chargingView}|${revision}`;
}

function ensureChargingAnalytics(selected='current') {
  if(chargingTab==='parameters') return;
  const key=chargingAnalyticsKey(selected);
  if(key===chargingAnalyticsLoadedKey||key===chargingAnalyticsLoadingKey) return;
  loadChargingAnalytics(selected,key);
}

async function loadChargingAnalytics(selected='current',key=chargingAnalyticsKey(selected)) {
  const request=++chargingAnalyticsRequest;
  chargingAnalyticsLoadingKey=key;
  chargingAnalyticsBusy=true; chargingAnalyticsError='';
  if(page==='energy') renderChargingWorkspace();
  try {
    if(chargingTab==='statistics') chargingStats=await api(`/api/charging/statistics?days=${chargingDays}&mode=${chargingMode}`);
    else if(chargingTab==='process') {
      const result=await api(`/api/charging/process?id=${encodeURIComponent(selected)}&view=${chargingView}`);
      if(request!==chargingAnalyticsRequest||key!==chargingAnalyticsKey(selected)||page!=='energy') return;
      chargingSession=result.session;chargingSeries=result.series;
      chargingPoint=Math.min(chargingPoint,Math.max(0,(result.series.points||[]).length-1));
    }
    if(request===chargingAnalyticsRequest) chargingAnalyticsLoadedKey=key;
  } catch(error) { if(request===chargingAnalyticsRequest) chargingAnalyticsError=error.message; }
  finally { if(request===chargingAnalyticsRequest){chargingAnalyticsLoadingKey='';chargingAnalyticsBusy=false;renderChargingWorkspace();} }
}

function renderChargingWorkspace() {
  const target=$('.charging-workspace');
  if(target&&page==='energy') {
    const open=[...target.querySelectorAll('details[open][data-detail]')].map(item=>item.dataset.detail);
    const focused=document.activeElement?.closest('[data-detail]')?.dataset.detail;
    target.outerHTML=chargingWorkspace(state?.model?.charging_details);
    open.forEach(key=>{const item=document.querySelector(`[data-detail="${CSS.escape(key)}"]`);if(item)item.open=true;});
    if(focused) document.querySelector(`[data-detail="${CSS.escape(focused)}"] summary`)?.focus();
  }
}

function chargeHistoricalParameters(details) {
  if (!details) return `<p class="charge-note">这条旧记录未保存充电参数；不使用当前车辆状态补填。</p>`;
  const metrics=details.metrics || {};
  const stats=[['采样峰值功率',metrics.sampled_peak_kw,'kW'],['时间加权平均功率',metrics.average_power_kw,'kW'],['有效功率样本',metrics.power_sample_count,'个'],['功率覆盖率',Number.isFinite(metrics.power_coverage)?metrics.power_coverage*100:null,'%'],['功率覆盖时长',metrics.power_covered_seconds,'秒'],['确认充电覆盖时长',metrics.charging_time_covered_seconds,'秒'],['充电时间覆盖率',Number.isFinite(metrics.charging_time_coverage)?metrics.charging_time_coverage*100:null,'%'],['续航增加',metrics.range_delta_km,'km'],['最大车辆数据间隔',metrics.max_state_gap_seconds,'秒'],['最大采集间隔',metrics.max_observed_gap_seconds,'秒'],['停止检测数据间隔',metrics.stop_detection_state_gap_seconds,'秒'],['停止检测采集间隔',metrics.stop_detection_observed_gap_seconds,'秒'],['尾段功率下降',metrics.tail_power_drop_percent,'%']];
  const mode=snapshot=>snapshot?.mode==='ac'?'交流':snapshot?.mode==='dc'?'直流':'未知';
  const status=snapshot=>snapshot?.charging===true?'充电中':snapshot?.charging===false?'未充电 / 已停止':'未知';
  return `<div class="charge-saved-details"><h3>已保存充电参数</h3>${row('起止充电模式',`${mode(details.start)} → ${mode(details.end)}`)}${row('起止充电状态',`${status(details.start)} → ${status(details.end)}`)}${row('起止观测功率',`${chargeNumber(details.start?.power_kw,'kW')} → ${chargeNumber(details.end?.power_kw,'kW')}`)}<div class="charging-parameter-grid">${stats.slice(0,4).map(([label,value,unit])=>`<div class="charging-parameter"><span>${label}</span><strong>${esc(chargeNumber(value,unit))}</strong></div>`).join('')}</div><details class="car-disclosure" data-detail="charge-saved-parameters"><summary><span>全部起止参数与采样质量</span></summary><div class="charge-saved-body">${row('起点车辆数据时间',eventTime(details.start?.state_time))}${row('终点车辆数据时间',eventTime(details.end?.state_time))}${row('起点采集时间',eventTime(details.start?.observed_at))}${row('终点采集时间',eventTime(details.end?.observed_at))}${stats.slice(4).map(([label,value,unit])=>row(label,chargeNumber(value,unit))).join('')}${chargingParameterGroups(details.start,details.end)}${chargingUnavailable()}</div></details><p class="energy-caption">仅比较该次充电已保存观测；部分记录的起点是首次观测，不是实际开始。峰值仅为采样峰值；平均功率需足够样本与覆盖率，缺失不等于零。</p></div>`;
}

function chargeDetail(event) {
  if (!event) return `<section class="card charge-detail" id="charge-detail">${empty('选择一条充电记录','从左侧列表选择记录后，在这里查看起止时间、电量变化和完整性。','energy')}</section>`;
  const format=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1}).format(value):'未知';
  const validDelta=Number.isFinite(event.start_soc)&&Number.isFinite(event.end_soc)&&event.end_soc>event.start_soc;
  const delta=validDelta?event.end_soc-event.start_soc:null;
  const estimated=!event.partial&&validDelta&&Number.isFinite(event.battery_capacity_kwh)&&event.battery_capacity_kwh>0
    ? event.battery_capacity_kwh*delta/100 : null;
  const estimate=Number.isFinite(estimated)?`${format(estimated)} kWh（估算）`:'充入电量无法估算';
  const note=event.partial?'这是部分记录，仅表示已观测 SOC 变化，不作为完整充电量。':
    Number.isFinite(estimated)?'估算使用该事件保存的电池容量与 SOC 变化，不代表充电桩结算电量。':'该事件缺少有效容量或 SOC 数据，未使用当前车型配置补算。';
  return `<section class="card charge-detail" id="charge-detail"><div class="card-head"><div><h2>充电详情</h2><p class="card-meta">${esc(eventTime(event.end_time))}</p></div>${pill(event.partial?'部分记录':'完整记录',event.partial?'warn':'good')}</div><div class="charge-soc"><div><span>起始 SOC</span><strong>${format(event.start_soc)}${Number.isFinite(event.start_soc)?'<small>%</small>':''}</strong></div><div class="charge-soc-line" aria-hidden="true"><i></i></div><div><span>结束 SOC</span><strong>${format(event.end_soc)}${Number.isFinite(event.end_soc)?'<small>%</small>':''}</strong></div></div><div class="card-body charge-facts">${row('记录起点',eventTime(event.start_time))}${row('结束时间',eventTime(event.end_time))}${row('记录时长',eventDuration(event.duration_seconds))}${row('电量增加',Number.isFinite(delta)?`${format(delta)} 个百分点`:'未知')}${row('估算充入电量',estimate)}</div><div class="charge-note ${event.partial?'warning':''}">${esc(note)}</div>${startEvidenceView(event.start_evidence)}${chargeHistoricalParameters(event.charging_details)}</section>`;
}

function chargeHistoryBody() {
  if (chargeBusy && !chargeEvents.length) return `<div class="charge-loading" role="status">正在读取充电记录…</div>`;
  if (chargeError) return `${empty('充电记录读取失败',chargeError,'energy')}<div class="charge-empty-action"><button class="button secondary" data-action="charge-retry">重试</button></div>`;
  if (!chargeEvents.length) return `${empty('该日期暂无充电记录','已结束的本地充电记录会显示在这里；尚未确认结束的会话不会列入。','energy')}<div class="charge-empty-action"><button class="button secondary" data-action="charge-latest">返回最近记录</button></div>`;
  return `<div class="charge-records">${chargeEvents.map((event,index)=>`<button class="charge-record ${chargeSelected?.id===event.id?'selected':''}" data-action="charge-select" data-event-id="${esc(event.id)}" aria-label="查看充电记录 ${index+1}" ${chargeSelected?.id===event.id?'aria-current="true"':''}><div><strong>${esc(eventTime(event.end_time))}</strong><span>${event.partial?'部分记录':'完整记录'}</span></div><div><b>${Number.isFinite(event.start_soc)?`${esc(event.start_soc)}%`:'未知'} 至 ${Number.isFinite(event.end_soc)?`${esc(event.end_soc)}%`:'未知'}</b><span>${esc(eventDuration(event.duration_seconds))}</span></div></button>`).join('')}</div><div class="event-pagination"><button class="button secondary" data-action="charge-prev" ${chargeCursorStack.length?'':'disabled'}>上一页</button><button class="button secondary" data-action="charge-next" ${chargeNextCursor?'':'disabled'}>下一页</button></div>`;
}

function renderChargeHistory() {
  const list=$('#charge-list');
  if (!list) return;
  list.innerHTML=chargeHistoryBody();
  const detail=$('#charge-detail');
  if (detail) {
    const opened=detail.querySelector('details[open]')!==null;
    detail.outerHTML=chargeDetail(chargeSelected);
    const saved=$('#charge-detail details');
    if (saved && opened) saved.open=true;
  }
}

async function loadChargeEvents(version) {
  const request=++chargeRequest;
  chargeBusy=true;chargeError='';renderChargeHistory();
  try {
    const result=await api(`/api/events?date=${encodeURIComponent(chargeDate)}&kind=charge_end${chargeCursor?`&cursor=${encodeURIComponent(chargeCursor)}`:''}`);
    if(request!==chargeRequest||generation!==version||page!=='energy') return;
    chargeEvents=result.events||[];chargeNextCursor=result.next_cursor||null;
    const selected=chargeSelected&&chargeEvents.find(item=>item.id===chargeSelected.id);
    if (selected) chargeSelected=selected;
    else if (!chargeSelected) chargeSelected=chargeEvents[0]||null;
  } catch(error) {
    if(request!==chargeRequest||generation!==version||page!=='energy') return;
    chargeEvents=[];chargeNextCursor=null;chargeError=error.message;
  } finally {
    if(request===chargeRequest&&generation===version&&page==='energy'){chargeBusy=false;renderChargeHistory();}
  }
}

function overview() {
  if (!state?.model) return modelRequired();
  const m = state.model, profile=state.profile || {name:'我的车辆',variant:'',image:''};
  const closure=m.closure || {doors:'未知',windows:'未知',trunk:'未知'};
  const recording=state.recording;
  const recent=state.recent_events || {};
  const activity=state.monitoring?.charge==='charging'?'充电记录中':state.monitoring?.trip==='driving'?'行程记录中':state.monitoring?.trip==='waiting'?'等待行程结束确认':'没有进行中活动的证据';
  const recordingLabel={never:'尚未开启',paused:'已暂停',active:'正在记录',failed:'采集失败',offline:'后台未在线'}[recording.status] || (recording.active?'正在记录':'已暂停');
  return `<section class="hero"><div class="hero-copy"><div class="hero-title">${esc(profile.name)}</div><div class="hero-state">${pill(m.lock.confirmed?m.lock.value:'锁车状态未知',m.lock.confirmed?'good':'warn',m.lock.confirmed?'lock':'info')}${pill(m.charging.confirmed?m.charging.value:'充电状态未知',m.charging.confirmed?'':'warn','energy')}</div><div class="freshness">${icon('clock')}<div>${age(m.updated_time,'车辆数据更新于 ')}<span class="subtle">云端缓存 · 不代表实时状态</span></div></div><button class="closure-summary" data-page="car" aria-label="查看门窗详情">${[['doors','车门'],['windows','车窗'],['trunk','尾门']].map(([key,label])=>`<span class="${closure[key]==='未知'?'unknown':''}">${label}${esc(closure[key])}</span>`).join('')}${icon('arrow')}</button></div><div class="hero-car">${profile.image?`<img src="${esc(profile.image)}" alt="${esc(profile.image_alt)}">`:icon('car')}</div></section>
  <section class="metric-grid overview-metrics">${metric('动力电池',m.metric_details?.battery || m.metrics.battery,'battery','',true)}${metric('预估续航',m.metric_details?.range || m.metrics.range,'range','以车辆实际表现为准')}</section>
  <div class="overview-secondary"><span>累计里程 <strong>${esc(m.metrics.odometer)}</strong></span><details class="data-explanation"><summary>数据说明与完整时间</summary><div class="explanation-content"><p>动力电池使用动力电池专用字段，与低压电池分开。续航是车辆返回的估计。</p><p>胎压轮位及单位已核对；总览四舍五入至一位小数，车辆详情保留接口精度。未设置未经核对的胎压报警阈值。</p><p>门窗及锁车仅解释本车已验证的组合；未知不代表正常，也不代表异常。车型图片仅供参考。</p>${row('车辆状态时间',m.updated_at)}${row('温度状态时间',m.temperature_updated_at)}${row('最近云端读取',state.read_at)}</div></details></div>
  <div class="grid-two"><section class="card"><div class="card-head"><h2>座舱与环境</h2>${link('车辆详情','car')}</div><div class="card-body"><div class="temperature"><div><div class="small-label">车内温度</div><div class="temp-value">${esc(m.metrics.inside)}</div></div><div><div class="small-label">车外温度</div><div class="temp-value">${esc(m.metrics.outside)}</div></div></div><div class="divider"></div><div class="subtle">${age(m.temperature_updated_time,'温度更新于 ')} · 与整车状态可能不同步</div></div></section>
  <section class="card"><div class="card-head"><h2>轮胎状态</h2>${link('查看详情','car')}</div><div class="card-body">${tyres(true)}</div></section></div>
  <div class="grid-two grid-equal overview-links recent-events"><section class="card"><div class="card-head"><h2>最近观测活动</h2>${link('查看行程','tracks')}</div><div class="card-body">${row('当前活动',activity)}${row('本地采集',recordingLabel)}${recording.error?`<p class="unknown">${esc(recording.error)}</p>`:''}<p class="subtle">状态来自后台最近观测，不代表车辆实时状态。</p></div></section><section class="card"><div class="card-head"><h2>最近完成行程</h2>${link('行程详情','tracks')}</div><div class="card-body">${eventSummary(recent.trip_end,'trip_end')}</div></section><section class="card"><div class="card-head"><h2>最近完成充电</h2>${link('能源详情','energy')}</div><div class="card-body">${eventSummary(recent.charge_end,'charge_end')}</div></section><section class="card"><div class="card-head"><h2>位置</h2>${link('打开地图','map')}</div><div class="card-body"><div class="location-preview">${icon('map')}<span>${showPosition?'位置显示已开启 · 前往地图查看':'位置默认隐藏 · 按需打开地图'}</span></div></div></section></div>`;
}

function table(fields, paths = false) {
  if (!fields.length) return empty('暂无对应参数','接口尚未返回这一组字段；不以零值填充。');
  return `<div class="table-wrap"><table class="fields"><thead><tr><th>参数</th><th>当前值 / 原值</th><th>解释依据</th></tr></thead><tbody>${fields.map(f => `<tr><td>${esc(f.name)}${paths ? `<span class="field-path">${esc(f.path)}</span>` : ''}</td><td><span class="field-value">${esc(f.value)}</span>${f.evidence === '待核实' ? '<span class="field-path">原始值，含义待核对</span>' : ''}</td><td>${pill(f.evidence,f.evidence==='待核实'||f.evidence==='未知'?'warn':'')}</td></tr>`).join('')}</tbody></table></div>`;
}

// Classify interpreted labels only. Never translate unverified cloud enums here.
function carStateKind(value) {
  if (['关闭','已锁','已锁车'].includes(value)) return 'safe';
  if (['打开','开启','未锁','未锁车'].includes(value)) return 'attention';
  return 'unknown';
}
function carState(value) {
  const kind = carStateKind(value);
  return `<span class="car-state state-${kind}">${esc(kind === 'unknown' ? '未知' : value)}</span>`;
}
function carPhoto() {
  // The configured overview SVG wraps this exact official PNG. Keep the
  // existing profile association so an unconfigured vehicle gets no wrong model.
  const profile = state.profile;
  if (profile?.image !== '/car.svg') return '<div class="car-photo-empty">车型图片待配置</div>';
  return `<figure class="car-photo"><img src="/car-001.png" alt="${esc(profile.image_alt || profile.name)}"></figure>`;
}
function carDisclosure(key, label, fields) {
  const uncertain = fields.filter(f => ['未知','待核实'].includes(f.evidence)).length;
  return `<details class="car-disclosure" data-detail="${key}"><summary><span>${label}</span><span class="car-detail-count">${fields.length ? `${fields.length} 项${uncertain ? ` · ${uncertain} 项待核实 / 未知` : ''}` : '暂无返回数据'}</span></summary>${table(fields,true)}</details>`;
}
function car() { return vehiclePage.render(carOverview,modelRequired); }
function carOverview() {
  if (!state?.model) return modelRequired();
  const m = state.model;
  const pm25 = m.fields.find(field => field.group === '空气质量' && field.key === 'interiorPM25')?.value;
  const hasPm25 = (typeof pm25 === 'number' || (typeof pm25 === 'string' && pm25.trim() !== '')) && Number.isFinite(Number(pm25)) && Number(pm25) >= 0;
  const positions = ['左前','右前','左后','右后'];
  const doors = positions.map(name => m.doors.find(d => d.name === name) || {name,door:'未知',lock:'未知',window:'未知',raw:{}});
  const labels = [['door','车门'],['lock','门锁'],['window','车窗']];
  const lock = m.lock.confirmed ? m.lock.value : '未知';
  const statuses = doors.flatMap((d,i) => labels.map(([key,label]) => ({name:d.name+label,value:d[key],target:'car-door-'+i})))
    .concat([{name:'中控锁',value:lock,target:'car-center-lock'},{name:'尾门',value:m.trunk,target:'car-trunk'},{name:'前舱盖',value:m.hood,target:'car-hood'}]);
  const attention = statuses.filter(item => carStateKind(item.value) === 'attention');
  const unknown = statuses.filter(item => carStateKind(item.value) === 'unknown');
  const doorCards = doors.map((d,i) => `<article id="car-door-${i}" tabindex="-1" class="car-door car-door-${i}" data-position="${d.name}"><h3>${d.name}<span>${['主驾','副驾','后排','后排'][i]}</span></h3>${labels.map(([key,label]) => `<div class="inline-row"><span>${label}</span>${carState(d[key])}</div>`).join('')}</article>`).join('');
  const doorFields = doors.flatMap(d => labels.map(([key,label]) => ({name:d.name+label,value:d.raw?.[key] ?? '未知',evidence:carStateKind(d[key]) === 'unknown' ? '待核实' : '本车已核对'})));
  const climateFields = m.fields.filter(f => f.group === '空调与舒适' && !/^(winPos|winStatus)/.test(f.key) && !['interiorTemp','exteriorTemp','temperatureUpdateTime'].includes(f.key));
  const equipment = f => /sunroof|curtain/i.test(f.key) || /^(rl|rr)Vent/.test(f.key);
  const seat = f => /^(drv|pass|rl|rr|steerWhl)/.test(f.key);
  return `<section class="car-summary" aria-label="车辆状态摘要">
    <div class="car-summary-heading"><div><h2>门窗与锁止状态</h2><p class="car-caption">以下计数仅含门窗与锁止，共 15 项</p></div><div class="car-art">${carPhoto()}</div></div>
    <div class="car-summary-top"><div class="car-freshness">${icon('clock')}<strong>${age(m.updated_time,'车辆数据更新于 ')}</strong><span>云端缓存 · 不代表实时状态</span></div><div class="car-summary-counts"><span class="car-state state-${attention.length ? 'attention' : 'neutral'}">需关注 ${attention.length} 项</span><span class="car-state state-${unknown.length ? 'unknown' : 'neutral'}">未知 ${unknown.length} 项</span></div></div>
    <div class="car-summary-stats">${labels.map(([key,label]) => { const count = doors.filter(d => carStateKind(d[key]) === 'safe').length; return `<div><span>${label}</span><strong class="state-${count === 4 ? 'safe' : 'unknown'}">${count}<small> / 4</small></strong><span>${key === 'lock' ? '已确认锁止' : '已确认关闭'}</span></div>`; }).join('')}</div>
    ${attention.length ? `<div class="car-attention-list">${attention.map(item => `<span>${esc(item.name)} · ${esc(item.value)}</span>`).join('')}</div>` : ''}
    ${unknown.length || attention.length ? `<details class="car-pending" data-detail="car-pending"><summary>定位未知与需关注项 · ${unknown.length+attention.length} 项</summary><div class="car-pending-list">${[...attention,...unknown].map(item=>`<button data-vehicle="locate" data-target="${item.target}">${esc(item.name)} · ${carStateKind(item.value)==='unknown'?'未知':esc(item.value)}</button>`).join('')}</div></details>` : ''}
    <p class="car-summary-note">${unknown.length ? '未知项请在下方逐项查看；未知不代表正常或异常。' : '以上为缓存快照中的门窗状态。'}</p>
  </section>
  <div class="car-main-grid"><section class="card car-closures"><div class="card-head"><h2>门锁、车门与车窗</h2><span class="car-caption">左舵车辆 · 只读状态</span></div><div class="card-body">
    <div class="car-vehicle-grid"><div id="car-hood" tabindex="-1" class="car-end car-hood"><span>车头 · 前舱盖</span>${carState(m.hood)}</div>${doorCards}<div id="car-trunk" tabindex="-1" class="car-end car-trunk"><span>车尾 · 尾门</span>${carState(m.trunk)}</div></div>
    <div id="car-center-lock" tabindex="-1" class="car-lock-row"><span>${icon('lock')}中控锁</span>${carState(lock)}</div>
    <p class="car-caption car-legend"><span class="state-safe">关闭 / 锁止</span><span class="state-attention">打开 / 未锁</span><span class="state-unknown">未知</span><span>状态以文字为准</span></p>
  </div></section>
  <div class="car-secondary"><section class="card car-tyres"><div class="card-head"><h2>四轮胎压与胎温</h2><span class="car-caption">车头朝上</span></div><div class="card-body"><div class="tyre-grid car-wheel-grid">${positions.map(name => { const t = m.tyres.find(t => t.name === name); return `<div class="car-wheel" data-position="${name}"><span class="car-wheel-name">${name}</span><strong>${esc(t?.pressure ?? '未知')}</strong><span>胎温 ${esc(t?.temperature ?? '未知')}</span></div>`; }).join('')}</div><div class="car-tyre-time">${age(m.updated_time,'整车快照更新于 ')} · 轮胎独立时间未提供</div><p class="car-caption car-tyre-note">保留接口精度；暂无已核对的胎压报警阈值。</p></div></section>
  <section class="card car-cabin"><div class="card-head"><h2>座舱与环境</h2></div><div class="card-body"><div class="temperature"><div><div class="small-label">车内温度</div><div class="temp-value">${esc(m.metrics.inside)}</div></div><div><div class="small-label">车外温度</div><div class="temp-value">${esc(m.metrics.outside)}</div></div></div><div class="car-temperature-time">${icon('clock')}${age(m.temperature_updated_time,'温度更新于 ')}</div><p class="car-caption">温度与整车状态可能不同步</p><div class="car-pm25"><div class="car-pm25-reading"><span class="small-label">车内 PM2.5</span><strong class="car-pm25-value">${hasPm25 ? esc(pm25) : '暂无数据'}</strong></div><p class="car-caption">${hasPm25 ? '单位待核实 · 独立更新时间未提供' : '未返回有效读数'}</p></div></div></section></div></div>
  <section class="card car-data"><div class="card-head"><h2>参数与数据详情</h2><button class="text-link" data-vehicle="parameters">全部参数${icon('arrow')}</button></div><p class="card-meta">按需展开查看。待核实参数不代表本车配备或正在运行该设备。</p>
    <details class="car-disclosure" data-detail="closures"><summary><span>门窗数据与解释依据</span><span class="car-detail-count">四门 / 中控锁 / 尾门 / 前舱盖</span></summary><p class="car-disclosure-note">原值仅用于核对。只解释本车已核对组合；其他值显示未知，不从单个编码推测开闭或锁止。</p>${table(doorFields)}${table(m.fields.filter(f => /^(winStatus|doorPos)/.test(f.key) || ['centralLockingStatus','trunkOpenStatus','trunkLockStatus','engineHoodOpenStatus'].includes(f.key)),true)}</details>
    ${carDisclosure('climate','空调相关参数',climateFields.filter(f => !equipment(f) && !seat(f)))}
    ${carDisclosure('seats','座椅与方向盘',climateFields.filter(f => !equipment(f) && seat(f)))}
    ${carDisclosure('air','空气质量',m.fields.filter(f => f.group === '空气质量'))}
    ${carDisclosure('equipment','待核实设备',climateFields.filter(equipment))}
    <details class="car-disclosure" data-detail="times"><summary><span>完整时间与数据说明</span></summary><div class="car-disclosure-note">${row('车辆状态时间',m.updated_at)}${row('温度状态时间',m.temperature_updated_at)}${row('最近云端读取',state.read_at)}<p>刷新会重新读取云端缓存，不保证车辆产生新数据。胎压与胎温按左舵车辆轮位展示；不使用未经核对的报警阈值。</p></div></details>
  </section>`;
}

function energy() {
  if (!state?.model) return modelRequired();
  if (!chargeDateInitialized) {
    const latestEnd=state.recent_events?.charge_end?.end_time;
    chargeDate=beijingDate(Number.isFinite(latestEnd)?latestEnd:Date.now());
    chargeDateInitialized=true;
  }
  const m = state.model, profile = state.profile || {};
  const battery = m.metric_details?.battery?.value, range = m.metric_details?.range?.value;
  const validBattery = Number.isFinite(battery) && battery >= 0 && battery <= 100;
  const validRange = Number.isFinite(range) && range >= 0;
  const rated = profile.range_km;
  const validRated = Number.isFinite(rated) && rated > 0 && ['CLTC','WLTP','NEDC','EPA'].includes(profile.range_standard);
  const trip = state.range_attainment || {status:'no_trip'};
  const canCalculate = trip.status === 'available' && Number.isFinite(trip.ratio);
  const reasons = {no_trip:'等待后台记录并确认一段完整行程。', incomplete:'最近行程存在观测缺口或跨充电，无法计算。', invalid:'最近行程的里程、电量或时间数据无效。', no_consumption:'最近行程耗电为零或电量回升，无法计算。', no_rating:'当前车型缺少有效标称续航。', unavailable:'行程记录暂不可用，请稍后重试。'};
  const format = value => new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1}).format(value);
  const electric = m.fields.filter(f => f.group === '能源与充电' || f.path === 'additionalVehicleStatus.chargeHvSts');
  const remainingTime = m.charging.remaining_time || '未知';
  const electricKeys = ['chargeUAct','chargeIAct','dcChargeSts','dcChargeIAct','dcChargePileUAct','dcChargePileIAct','chargeHvSts','hvTempLevel','ptReady'];
  const strategyKeys = ['bookChargeSts','chargeLidAcStatus','chargeLidDcAcStatus','disChargeSts','disChargeConnectStatus','disChargeUAct','disChargeIAct','timeToTargetDisCharged'];
  const primaryKeys = ['chargeLevel','distanceToEmptyOnBatteryOnly','chargeSts','chargerState','statusOfChargerConnection','timeToFullyCharged'];
  const other = electric.filter(f => ![...electricKeys,...strategyKeys,...primaryKeys].includes(f.key));
  return `<section class="energy-freshness">${icon('clock')}<strong>${age(m.updated_time,'车辆数据更新于 ')}</strong><span>云端缓存 · 不代表实时状态</span></section>
  <div class="energy-top">
    <section class="card energy-battery"><div class="card-head"><h2>动力电池与续航</h2>${pill('动力电池','', 'battery')}</div>
      <div class="energy-primary"><div><span>当前电量</span><strong>${validBattery ? format(battery) : '未知'}${validBattery ? '<small>%</small>' : ''}</strong></div><div><span>剩余续航</span><strong>${validRange ? format(range) : '未知'}${validRange ? '<small>km</small>' : ''}</strong></div></div>
      <div class="energy-battery-track" ${validBattery ? `role="meter" aria-label="动力电池电量" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${battery}"` : 'aria-label="电量未知"'}><div style="width:${validBattery ? battery : 0}%"></div></div>
      <div class="energy-rating"><div><span>标称续航${validRated ? `（${esc(profile.range_standard)}）` : ''}</span><strong>${validRated ? `${format(rated)} <small>km</small>` : '待配置'}</strong></div><span>${esc(profile.variant || '车型资料待配置')}</span></div>
    </section>
    <section class="card energy-charge"><div class="card-head"><h2>当前充电状态</h2>${pill(m.charging.confirmed ? m.charging.value : '充电状态未知',m.charging.confirmed ? '' : 'warn','energy')}</div><div class="card-body"><div class="energy-current-soc"><span>当前电量</span><strong>${validBattery?`${format(battery)}%`:'未知'}</strong></div>
      <div class="energy-charge-grid">${[['充电模式',m.charging.mode==='dc'?'直流充电':m.charging.mode==='ac'?'交流充电':'未知'],['预计剩余时间',remainingTime],['连接状态',m.charging.connection_state || '接口未提供有效连接判断']].map(([label,value]) => `<div><span>${label}</span><strong>${esc(value)}</strong></div>`).join('')}</div><p class="energy-caption">${esc(m.charging.detail || '证据不足，暂无法确认充电状态。')}</p><p class="energy-caption">状态来自车辆云端缓存；缺少会话起点时不推测充电开始时间。</p></div></section>
  </div>
  ${chargingWorkspace(m.charging_details)}
  <section class="card energy-achievement"><div class="card-head"><h2>续航与行程参考</h2>${pill('最近已结束行程')}</div><div class="card-body"><div class="energy-ratio">${canCalculate ? `${trip.ratio.toFixed(1)}<small>%</small>` : `<span>${trip.status === 'no_trip' ? '暂无可计算行程' : '无法计算'}</span>`}</div>
      <p class="energy-caption">${canCalculate ? `按实际行驶里程与耗电量，对比 ${esc(trip.standard)} 标称续航` : esc(reasons[trip.status] || reasons.invalid)}</p>
      ${canCalculate ? `<div class="energy-reference">${row('实际行驶里程',`${format(trip.distance_km)} km`)}${row('起止电量',`${format(trip.start_soc)}% 至 ${format(trip.end_soc)}%`)}${row('消耗电量',`${format(trip.used_soc)} 个百分点`)}${row('对应标称里程',`${format(trip.reference_km)} km`)}</div>` : ''}
      ${trip.start_at && trip.end_at ? `<p class="energy-caption energy-trip-time">行程开始：${esc(trip.start_at)}<br>行程结束：${esc(trip.end_at)}</p>` : ''}
      <p class="energy-caption">基于后台记录的里程与电量变化；下电确认 10 分钟后生成。电量取整及云端缓存延迟会影响精度。</p>
    </div></section>
  <section class="card car-data energy-details"><div class="card-head"><h2>能源详情</h2>${link('全部参数','fields')}</div><p class="card-meta">展开查看参数原值、单位验证情况与计算依据。</p>
    <details class="car-disclosure" data-detail="energy-formula"><summary><span>续航计算依据</span></summary><div class="car-disclosure-note"><p>达成率 = 实际行驶里程 ÷（标称续航 × 消耗电量百分点 ÷ 100）× 100%。消耗电量为同一行程起点电量减终点电量；里程为行程起止总里程之差。不使用当前剩余续航计算。</p><p>仅使用当前车辆最近一次已结束行程；不完整、跨充电、电量未下降或数据无效时不计算，不回退展示更早行程的结果。结果可超过 100%。</p><p>标称值来源：${esc(profile.range_source || '暂无来源资料')}。标准工况续航是车型参考值。</p><p>例如行驶 80 km，电量从 80% 降至 60%，标称 546 km，对应标称里程 109.2 km，达成率约 73.3%。短行程受电量取整影响较大，结果不用于判断电池健康。</p></div></details>
    ${carDisclosure('energy-status','充电状态原值',electric.filter(f => primaryKeys.includes(f.key)))}
    ${carDisclosure('energy-electric','电压、电流与高压参数',electric.filter(f => electricKeys.includes(f.key)))}
    ${carDisclosure('energy-strategy','预约、充电口与对外放电',electric.filter(f => strategyKeys.includes(f.key)))}
    ${carDisclosure('energy-other','电耗与其他能源参数',other)}
    <details class="car-disclosure" data-detail="energy-low-voltage"><summary><span>低压电池</span><span class="car-detail-count">独立于动力电池</span></summary><p class="car-disclosure-note">低压电池电量与健康字段不代表动力电池状态；未验证电气单位保留原值。</p>${table(m.fields.filter(f => f.group === '低压电池'),true)}</details>
  </section>`;
}

function privacyGate(track = false) {
  return `<div class="map-empty">${icon(track?'tracks':'map')}<h2>${track?'按日期回看采样轨迹':'让位置，只在需要时出现'}</h2><p>显示位置后将加载 OpenStreetMap 底图，底图服务会收到对应区域的瓦片请求。经纬度文本默认隐藏。</p>${action('显示位置并加载地图','show-position')}<p class="subtle">随时可隐藏位置 · 不主动唤醒车辆</p></div>`;
}

function mapPage() {
  if (!state?.model) return modelRequired();
  if (!showPosition) return `<section class="card">${privacyGate()}</section>`;
  return `<div class="filters">${action('隐藏位置','hide-position','secondary')}${action('回到最近位置','recenter','secondary')}</div><div class="map-layout"><section class="card map-card"><div id="map" class="map-canvas" aria-label="车辆位置地图"></div><div id="map-status" class="map-status" role="status">正在读取最近位置…</div></section><section class="card"><div class="card-head"><h2>定位信息</h2></div><div class="map-meta" id="location-info"><div class="subtle">正在读取…</div></div></section></div>`;
}

function tracksPage() {
  const toolbar = `<div class="track-toolbar"><div class="tabs" aria-label="轨迹来源"><button class="tab ${trackSource==='local'?'active':''}" data-source="local">本地记录</button><button class="tab ${trackSource==='cloud'?'active':''}" data-source="cloud">云端历史</button></div><label><span class="subtle">北京时间 </span><input type="date" id="track-date" aria-label="轨迹日期" value="${esc(trackDate)}"></label></div>`;
  return toolbar + (trackSource === 'cloud' ? cloudHistoryPage() : localTripsPage());
}

function monitoringPanel() {
  const monitor = state?.monitoring || {status:'not_started',events:[]};
  const labels = {not_started:'尚未启用',fresh:'获得新数据',unchanged:'等待车辆更新',stale:'车辆缓存过旧',blocked:'需要处理',cooldown:'接口冷却中',retrying:'连接重试中',stopped:'已停止',paused:'已暂停',unavailable:'状态暂不可用'};
  const delivery = {pending:'等待发送',sending:'发送中',sent:'已发送',failed:'发送失败',uncertain:'发送结果待确认',cancelled:'已取消'};
  const kinds = {trip_end:'行程总结',charge_start:'开始充电',charge_end:'充电总结'};
  const activity = {waiting:'下电等待 10 分钟',driving:'行程记录中',idle:'暂无进行中的记录',charging:'充电记录中',unknown:'待确认'};
  const label = monitor.status === 'not_started' ? labels.not_started : monitor.online ? labels[monitor.status] || '运行中' : '监控未在线';
  return `<section class="card section-gap"><div class="card-head"><h2>自动行程与充电通知</h2>${pill(label,monitor.online && !['blocked','stale'].includes(monitor.status)?'good':'warn')}</div><div class="card-body"><p class="subtle">后台正常每 ${esc(state?.recording?.interval || 30)} 秒检查，停车、行驶和充电均保持此频率；故障或限流时退避。确认下电后等待 10 分钟发送行程总结；充电开始、停止时发送通知。云端数据延迟或缺失时，确认和通知也会延后。</p>${row('行程',activity[monitor.trip] || '待确认')}${row('充电',activity[monitor.charge] || '待确认')}${row('通知渠道','企业微信群机器人')}${monitor.error?`<p class="unknown">${esc(monitor.error)}</p>`:''}<p class="subtle">采集与通知共用一个后台任务。关闭浏览器不停止；下方暂停会同时暂停车辆检查和新事件检测，服务重启后默认恢复。</p>${(monitor.events || []).length?`<h3>最近通知</h3>${monitor.events.map(event=>row(kinds[event.kind] || '通知',delivery[event.delivery] || '未知')).join('')}`:'<p class="subtle">暂无通知记录。</p>'}</div></section>`;
}

function settings() {
  const recording = state?.recording || {active:true,interval:30,last_sample:'未知',last_new:'未知'};
  return `<section class="card"><div class="card-head"><h2>连接与隐私</h2>${pill('Web 服务已连接')}</div><div class="card-body"><div class="settings-row"><div><h3>账号会话</h3><p>${state?.authenticated?'已发现车辆会话；可用性以最近一次车辆读取结果为准。':'尚未登录。请在运行服务的设备上完成车辆登录。'}</p></div>${pill(state?.authenticated?'会话已保存':'未登录',state?.authenticated?'':'warn')}</div><div class="settings-row"><div><h3>位置显示</h3><p>地图及轨迹共用开关。隐藏后清除当前页面的地图与坐标；不会删除已有本地记录或停止采集。</p></div>${action(showPosition?'隐藏位置':'显示位置并加载地图',showPosition?'hide-position':'show-position','secondary')}</div></div></section>${monitoringPanel()}
  <section class="card section-gap"><div class="card-head"><h2>本地轨迹采集</h2>${pill(({active:'采集中',paused:'已暂停',failed:'需要处理',offline:'后台未在线'})[recording.status] || '等待后台',recording.status==='active'?'good':'warn')}</div><div class="card-body"><div class="notice info">${icon('info')}服务启动默认开启；由同一后台保存轨迹并检测行程和充电。暂停会同时停止自动检查与通知处理，已有记录保留。网络故障退避重试；账号失效需更新会话。</div><div class="settings-row"><div><h3>采样间隔</h3><p id="sampling-help">默认 30 秒，可调为 10–60 秒；停车保持相同间隔。更快查询不保证车辆上传更快，重复数据不会增加轨迹点。故障或限流时等待会延长。</p></div><div class="settings-control">${action(recording.active?'暂停采集':'开始采集','recording',recording.active?'secondary':'')}</div></div><div class="settings-row"><label for="interval">正常采样间隔（秒）</label><div class="settings-control"><input id="interval" type="number" min="10" max="60" step="1" aria-describedby="sampling-help" value="${esc(samplingDraft ?? recording.interval)}" ${busy?'disabled':''}>${action('保存间隔','save-interval','secondary')}</div></div>${row('已保存间隔', `${recording.interval} 秒`)}${row('后台最近等待间隔', `${recording.effective_interval || recording.interval} 秒`)}${row('最近采样检查',recording.last_sample)}${row('最近新增观测',recording.last_new)}${row('轨迹数据库大小',`${((state?.storage_bytes||0)/1024).toFixed(1)} KB`)}<div class="subtle">数据保存在运行服务的设备上；默认不自动删除历史记录。</div></div></section><section class="card section-gap"><div class="card-head"><h2>关于数据</h2></div><div class="card-body"><p class="subtle">界面依据已核对的字段规则解释车辆数据。社区接口可能变化；字段存在不代表硬件可用，更不代表远程控制已接入。</p>${row('历史轨迹接口',state?.history?.message || '待连接')}${row('Web 连接','当前页面已连接服务')}${row('数据来源','GW2 云端缓存')}</div></section>`;
}

function more() { return `<div class="more-grid">${['energy','fields','insights','settings'].map(key => `<button data-page="${key}">${icon(key)}${pages[key]}${icon('arrow')}</button>`).join('')}</div>`; }

function render() {
  const samplingFocused = page==='settings' && document.activeElement?.id==='interval';
  const managerNode=page==='tracks'&&trackSource==='local'&&tripManagementOpen?$('#trip-management'):null;
  const managerFocus=managerNode?.contains(document.activeElement)?document.activeElement:null;
  if(!(page==='tracks'&&trackSource==='local'&&tripManagementOpen))tripManager.suspend();
  const insightsNode = page === 'insights' ? document.getElementById('insights-workspace') : null;
  const insightsFocus = insightsNode?.contains(document.activeElement) ? document.activeElement : null;
  const vehicleFocus = page === 'car' ? vehiclePage.focusSnapshot() : null;
  prepareLocalTripRender();
  const fieldFocus = page === 'fields' ? reviewFocusSnapshot() : null;
  generation++;
  const carOpenDetails = ['car','energy'].includes(page) && $('#main').dataset.page === page
    ? [...document.querySelectorAll('#main details[data-detail][open]')].map(el => el.dataset.detail) : [];
  const carFocusedDetail = ['car','energy'].includes(page) ? document.activeElement?.closest('details[data-detail]')?.dataset.detail : null;
  if (map) { map.remove(); map = null; mapMarker = null; }
  syncCloudHistory();
  navigation();
  $('#main').dataset.page=page;
  updateConnection();
  $('.breadcrumb').textContent = `我的车库 / ${state?.profile?.name || '我的车辆'}`;
  const error = transientError || state?.error;
  const body = {overview,car,energy,map:mapPage,tracks:tracksPage,fields:fieldsPage,insights:()=>'<div id="insights-workspace"></div>',settings,more}[page]();
  $('#main').innerHTML = head() + (error ? `<div class="notice error" role="alert">${icon('info')}<p>${esc(error)}${state?.model?' · 下方保留上次读取的数据与原时间。':''}</p></div>` : '') + (['overview','car'].includes(page) && refreshMessage?`<div class="refresh-result" role="status">${esc(refreshMessage)}</div>`:'') + body + (state?.model ? `<div class="status-footer">本次读取 ${esc(state.read_at)} · 车辆状态更新 ${esc(state.model.updated_at)}</div>` : '');
  if(managerNode&&$('#trip-management')){$('#trip-management').replaceWith(managerNode);if(managerFocus?.isConnected)managerFocus.focus({preventScroll:true});}
  if (page === 'insights') {
    if (insightsNode) document.getElementById('insights-workspace').replaceWith(insightsNode);
    insightsPage.mount(document.getElementById('insights-workspace'));
    if (insightsFocus?.isConnected) insightsFocus.focus({preventScroll:true});
  }
  carOpenDetails.forEach(key => { const detail = $(`details[data-detail="${key}"]`); if(detail) detail.open = true; });
  if (carFocusedDetail) $(`details[data-detail="${carFocusedDetail}"] > summary`)?.focus({preventScroll:true});
  updateClock();
  if(samplingFocused) $('#interval')?.focus({preventScroll:true});
  if (page === 'car') {vehiclePage.restoreFocus(vehicleFocus);vehiclePage.ensure();}
  if (page === 'settings' && window.StorageManagement) window.StorageManagement.mount($('#main'),api);
  if (page === 'fields') {renderFields();reviewRestoreFocus(fieldFocus);}
  if (page === 'tracks' && trackSource === 'cloud') renderCloudMap();
  if (page === 'map' && showPosition && state?.model) loadLocation(generation);
  if (page === 'energy' && state?.model) { loadChargeEvents(generation); ensureChargingAnalytics(chargingSelection); }
  if (page === 'tracks' && trackSource === 'local') mountLocalTrips();
}

function createMap(center, zoom = 14, options = {}) {
  if (!window.L) throw Error('地图组件无法加载，请重启本机服务。');
  if (!$('#map').parentElement.querySelector('.map-theme-note')) {
    const note=document.createElement('p');note.className='map-theme-note';
    note.textContent='地图底图保持原配色，以保证道路与地名可读。';
    $('#map').after(note);
  }
  map = L.map('map', { attributionControl:true, scrollWheelZoom:false, ...options }).setView(center,zoom);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { minZoom:2,maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors' })
    .on('tileerror', () => { if ($('#map-status')) $('#map-status').textContent = '部分底图未加载，可稍后重试；位置标记仅依据已返回数据。'; }).addTo(map);
  return map;
}

async function loadLocation(version) {
  try {
    const location = await api('/api/location');
    if (generation !== version || !showPosition) return;
    $('#location-info').innerHTML = `${row('位置可信度',location.trusted?'接口标记可信':'位置未确认')}${row('整车缓存更新时间',location.updated_at)}${row('本次读取时间',location.read_at)}${row('GPS 采集时间','定位采集时间未提供')}${row('坐标系',location.coordinate_system)}<p class="subtle">${esc(location.transform)}。不以速度 0 判断停车。</p>${action(showCoordinates?'隐藏经纬度':'显示经纬度','coordinates','quiet')}${showCoordinates ? row('经纬度',location.valid?`${location.latitude.toFixed(6)}, ${location.longitude.toFixed(6)}`:'未知') : ''}`;
    if (!location.plottable) {
      $('#map').innerHTML = empty(location.valid?'坐标系尚未适配':'暂无有效位置',location.valid?'当前坐标系未核验与底图转换，暂不落点。':'接口未返回有效经纬度，不使用零点或演示位置代替。','map');
      $('#map-status').textContent = '未绘制位置';
      return;
    }
    createMap([location.latitude,location.longitude]);
    mapMarker = L.circleMarker([location.latitude,location.longitude],{radius:10,color:location.trusted?'#20776e':'#7e898a',weight:3,fillOpacity:.3}).addTo(map);
    mapMarker.bindTooltip(location.trusted?'接口标记可信 · 坐标对齐待核验':'位置未确认 · 候选位置');
    $('#map-status').textContent = location.trusted?'接口标记可信；缓存位置，坐标对齐待核验。':'灰色候选位置：本次可信标记为 false 或缺失，不代表已确认当前位置。';
  } catch (error) {
    if (generation !== version) return;
    $('#map').innerHTML = empty('位置读取失败',error.message,'map');
    $('#map-status').textContent = '位置不可用';
  }
}

function setPlayback(index, {pan=true} = {}) {
  const point = playback[index];
  if (!point || !map) return;
  if (mapMarker) mapMarker.remove();
  mapMarker = L.circleMarker([point.latitude,point.longitude],{radius:9,color:point.trusted?'#20776e':'#8a9391',fillOpacity:.35,weight:3}).addTo(map);
  if (pan) map.panTo([point.latitude,point.longitude],{animate:trackSource!=='cloud'});
  $('#playback-label').textContent = `${index+1} / ${playback.length} · ${point.time_label} · ${point.time_source} · ${trackSource==='cloud'?'云端轨迹点':point.trusted?'接口标记可信':'位置未确认'}`;
}

async function refresh() {
  if (busy || waitSeconds()>0) return;
  const selected = Number($('#vehicle-select')?.value || state?.vehicle || 1);
  busy = true; transientError = ''; render();
  try {
    state = await api('/api/refresh',{vehicle:selected});
    connectionFailures=0;
    refreshMessage=refreshMessages[state.refresh_result] || '已读取云端缓存。';
    toast(refreshMessage);
  } catch (error) {
    transientError = error.message;
    try { state = await api('/api/state',undefined,8000); connectionFailures=0; } catch { connectionFailures=2; }
    refreshMessage='';
  } finally { busy = false; render(); }
}

async function updateRecording(saveInterval = false) {
  if (busy) return;
  const interval = saveInterval ? Number($('#interval')?.value) : state.recording.interval;
  if (!Number.isInteger(interval) || interval<10 || interval>60) { toast('采样间隔须为 10–60 秒的整数。'); return; }
  busy=true;
  try {
    const payload = saveInterval ? {active:state.recording.active,interval} : {active:!state.recording.active};
    state = await api('/api/recording',payload);
    if(saveInterval) samplingDraft=null;
    transientError='';
    toast(saveInterval?`正常采样间隔已保存为 ${state.recording.interval} 秒。`:state.recording.active?'已启用统一采集，请查看后台运行状态。':'自动采集与通知检测已暂停，已有记录保留。');
  } catch(error) { transientError=error.message; }
  finally { busy=false;render(); }
}

document.addEventListener('click', event => {
  if (tripManager.handle(event)) return;
  if (insightsPage.handle(event)) return;
  if (vehiclePage.handle(event)) return;
  const target = event.target.closest('button');
  if (!target || target.disabled) return;
  if (target.dataset.openResearch) {page='insights';render();insightsPage.openField(target.dataset.openResearch);window.scrollTo(0,0);return;}
  if (target.dataset.reviewExperiment) {openExperimentReview(target.dataset.reviewExperiment,target.dataset.path,target.dataset.side);return;}
  if (target.dataset.openExperiment) {page='insights';render();insightsPage.openExperiment({id:target.dataset.openExperiment});window.scrollTo(0,0);return;}
  if (handleReviewAction(target)) return;
  if (handleCloudAction(target)) return;
  if (handleLocalTripAction(target)) return;
  if (target.dataset.page) { page=target.dataset.page; render(); window.scrollTo(0,0); return; }
  if (target.dataset.source) { trackSource=target.dataset.source; render(); return; }
  switch(target.dataset.action) {
    case 'refresh': refresh(); break;
    case 'reconnect': pollState(true); break;
    case 'show-position': showPosition=true;render();break;
    case 'hide-position': showPosition=false;showCoordinates=false;trackData=null;playback=[];if(cloudHistory){cloudHistory.detail=null;cloudHistory.detailBusy=false;cloudHistory.detailRequest++;}render();break;
    case 'coordinates': showCoordinates=!showCoordinates;render();break;
    case 'recenter': if(map && mapMarker) map.setView(mapMarker.getLatLng(),15);break;
    case 'reload-tracks': render();break;
    case 'charge-select': chargeSelected=chargeEvents.find(item=>item.id===target.dataset.eventId)||chargeSelected;chargingSelection=chargeSelected.id;renderChargeHistory();if(chargingTab==='process')loadChargingAnalytics(chargingSelection);break;
    case 'charge-next': if(chargeNextCursor){chargeCursorStack.push(chargeCursor);chargeCursor=chargeNextCursor;chargeSelected=null;loadChargeEvents(generation);}break;
    case 'charge-prev': if(chargeCursorStack.length){chargeCursor=chargeCursorStack.pop();chargeSelected=null;loadChargeEvents(generation);}break;
    case 'charge-retry': loadChargeEvents(generation);break;
    case 'charge-latest': chargeDate=beijingDate(Number.isFinite(state?.recent_events?.charge_end?.end_time)?state.recent_events.charge_end.end_time:Date.now());chargeCursor=null;chargeCursorStack=[];chargeSelected=null;chargeEvents=[];render();break;
    case 'charging-tab': chargingTab=target.dataset.tab;chargingAnalyticsError='';renderChargingWorkspace();ensureChargingAnalytics(chargingSelection);break;
    case 'charging-view': chargingView=target.dataset.view;chargingPoint=0;loadChargingAnalytics(chargingSelection);break;
    case 'stats-days': chargingDays=Number(target.dataset.days);chargingStats=null;loadChargingAnalytics();break;
    case 'stats-detail': chargingTab='process';chargeSelected={id:target.dataset.eventId};chargingSelection=target.dataset.eventId;chargingPoint=0;renderChargingWorkspace();loadChargingAnalytics(chargingSelection);break;
    case 'analytics-retry': loadChargingAnalytics(chargingSelection);break;
    case 'recording': updateRecording();break;
    case 'save-interval': updateRecording(true);break;
  }
});
document.addEventListener('input', event => {
  if (tripManager.handle(event)) return;
  if (insightsPage.handle(event)) return;
  if (vehiclePage.handle(event)) return;
  if(event.target.id==='interval') samplingDraft=event.target.value;
  if(event.target.id==='search') {search=event.target.value;renderFields();}
  if(event.target.id==='playback') {
    if (trackSource==='local') {stopLocalPlayback();displayLocalPoint(Number(event.target.value));}
    else setPlayback(Number(event.target.value));
  }
  if(event.target.id==='charging-point') {chargingPoint=Number(event.target.value);renderChargingWorkspace();}
});
document.addEventListener('change', event => {
  if (tripManager.handle(event)) return;
  if (insightsPage.handle(event)) return;
  if (vehiclePage.handle(event)) return;
  if(event.target.id==='group') {groupFilter=event.target.value;renderFields();}
  if(event.target.id==='unknown') {unknownOnly=event.target.checked;renderFields();}
  if(event.target.id==='track-date') {trackDate=event.target.value;render();}
  if(event.target.id==='local-playback-speed') {
    const playing=!!localTrips.timer;localTrips.speed=Number(event.target.value);
    if(playing)startLocalPlayback();
  }
  if(event.target.id==='charge-date') {chargeDate=event.target.value;chargeCursor=null;chargeCursorStack=[];chargeSelected=null;chargeEvents=[];render();}
  if(event.target.id==='charging-mode') {chargingMode=event.target.value;chargingStats=null;loadChargingAnalytics();}
  if(event.target.id==='vehicle-select') {chargeDateInitialized=false;chargeCursor=null;chargeCursorStack=[];chargeSelected=null;chargeEvents=[];chargingSelection='current';chargingSession=null;chargingSeries=null;chargingStats=null;chargingAnalyticsLoadedKey='';chargingAnalyticsLoadingKey='';refresh();}
});

async function pollState(force = false) {
  if(polling || busy || (!force && document.hidden)) return;
  polling=true;
  try {
    const latest=await api('/api/state',undefined,8000);
    const changed=!state || latest.read_time!==state.read_time || latest.error!==state.error ||
      latest.recording.interval!==state.recording.interval || latest.recording.active!==state.recording.active ||
      latest.recording.effective_interval!==state.recording.effective_interval || latest.recording.status!==state.recording.status || latest.recording.last_new!==state.recording.last_new ||
      latest.recording.last_sample!==state.recording.last_sample || latest.next_query_at!==state.next_query_at ||
      latest.request_key!==state.request_key || latest.vehicle!==state.vehicle ||
      latest.insights_context!==state.insights_context ||
      latest.trip_records_revision!==state.trip_records_revision ||
      JSON.stringify(latest.history)!==JSON.stringify(state.history) ||
      latest.snapshot_revision!==state.snapshot_revision ||
      JSON.stringify(latest.recent_events)!==JSON.stringify(state.recent_events) ||
      JSON.stringify(latest.field_reviews)!==JSON.stringify(state.field_reviews);
    const restarted=state && latest.request_key!==state.request_key;
    state=latest; connectionFailures=0;
    if(restarted) { transientError='';refreshMessage='';samplingDraft=null; }
    if(changed) {
      if(page==='tracks' && trackSource==='local' && refreshLocalTrips()) {updateConnection();updateClock();}
      else render();
    }
    else { if(page==='insights')insightsPage.mount($('#insights-workspace'));updateConnection();updateClock(); }
  } catch(error) {
    connectionFailures=state?connectionFailures+1:2;
    updateConnection();
    if(!state) $('#main').innerHTML=`<section class="card">${empty('本机服务未连接','检查本机服务后点击上方“重新连接”。')}</section>`;
  } finally {polling=false;}
}
pollState(true);
setInterval(pollState,5000);
setInterval(updateClock,1000);

document.querySelector("#logout").addEventListener("click", async () => {
  const response = await fetch("/auth/logout", {method:"POST", headers:{"Content-Type":"application/json"},body:"{}"});
  if(response.ok) location.replace("/");
});
