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
const pages = { overview: '总览', car: '车辆', energy: '能源与充电', map: '定位地图', tracks: '行程与轨迹', fields: '参数字典', settings: '设置', more: '更多' };
const descriptions = { overview: '', car: '门窗、轮胎与座舱，逐项查看。', energy: '查看当前观测状态、充电记录与计算依据。', map: '最近返回的位置，保留可信度与时间信息。', tracks: '留住走过的路，也如实保留数据的空白。', fields: '查看中文解释、原始字段与验证状态。', settings: '管理本机连接、隐私与轨迹采集。', more: '更多车辆信息与本机设置。' };
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.info}</svg>`;
let state = null, page = 'overview', busy = false, transientError = '', showPosition = false, showCoordinates = false;
let map = null, mapMarker = null, generation = 0, toastTimer;
let trackSource = 'local', trackDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year:'numeric',month:'2-digit',day:'2-digit' }).format(new Date());
let trackData = null, playback = [], search = '', groupFilter = '', unknownOnly = false;
let archiveVehicle = '';
let eventCursor = null, eventCursorStack = [], eventRequest = 0;
const beijingDate = value => new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
let chargeDate = beijingDate(Date.now()), chargeDateInitialized = false;
let chargeEvents = [], chargeSelected = null, chargeCursor = null, chargeCursorStack = [], chargeNextCursor = null, chargeBusy = false, chargeError = '', chargeRequest = 0;
let connectionFailures = 0, polling = false;
let refreshMessage = '';
const refreshMessages = {cached:'已复用本机缓存，未请求云端。',unchanged:'已读取云端，车辆数据未更新。',new:'已获得新车辆数据。',time_unknown:'已读取云端，车辆更新时间未知。'};

function navigation() {
  $('#navigation').innerHTML = Object.entries(pages).filter(([key]) => key !== 'more').map(([key, label]) => `<button class="nav-item ${page === key ? 'active' : ''}" data-page="${key}" ${page === key ? 'aria-current="page"' : ''}>${icon(key)}${label}</button>`).join('');
  $('#mobile-navigation').innerHTML = ['overview','car','map','tracks','more'].map(key => `<button data-page="${key}" class="${page === key || (key === 'more' && ['energy','fields','settings'].includes(page)) ? 'active' : ''}" aria-label="${pages[key]}">${icon(key)}<span>${{overview:'总览',car:'车辆',map:'地图',tracks:'轨迹',more:'更多'}[key]}</span></button>`).join('');
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
  return `<div class="page-head"><div><div class="eyebrow">MY ZEEKR / ${new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit'}).format(new Date())}</div><h1>${pages[page]}</h1><div class="subtle">${descriptions[page]}</div></div><div class="page-actions">${state?.vehicles?.length > 1 ? `<select id="vehicle-select" class="select" aria-label="选择车辆" >${state.vehicles.map(v => `<option value="${v.number}" ${v.number === state.vehicle ? 'selected' : ''}>${esc(v.label)}</option>`).join('')}</select>` : ''}<div class="refresh-control">${action(busy ? '读取中…' : '刷新状态','refresh','','refresh')}<span id="refresh-hint" class="subtle"></span></div></div></div>`;
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
  return `<section class="card charge-detail" id="charge-detail"><div class="card-head"><div><h2>充电详情</h2><p class="card-meta">${esc(eventTime(event.end_time))}</p></div>${pill(event.partial?'部分记录':'完整记录',event.partial?'warn':'good')}</div><div class="charge-soc"><div><span>起始 SOC</span><strong>${format(event.start_soc)}${Number.isFinite(event.start_soc)?'<small>%</small>':''}</strong></div><div class="charge-soc-line" aria-hidden="true"><i></i></div><div><span>结束 SOC</span><strong>${format(event.end_soc)}${Number.isFinite(event.end_soc)?'<small>%</small>':''}</strong></div></div><div class="card-body charge-facts">${row('开始时间',eventTime(event.start_time))}${row('结束时间',eventTime(event.end_time))}${row('记录时长',eventDuration(event.duration_seconds))}${row('电量增加',Number.isFinite(delta)?`${format(delta)} 个百分点`:'未知')}${row('估算充入电量',estimate)}</div><div class="charge-note ${event.partial?'warning':''}">${esc(note)}</div></section>`;
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
  if (detail) detail.outerHTML=chargeDetail(chargeSelected);
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
  return `<section class="hero"><div class="hero-copy"><div class="hero-title">${esc(profile.name)}</div><div class="hero-sub">${esc(profile.variant)}</div><div class="hero-state">${pill(m.lock.confirmed?m.lock.value:'锁车状态未知',m.lock.confirmed?'good':'warn',m.lock.confirmed?'lock':'info')}${pill(m.charging.confirmed?m.charging.value:'充电状态未知',m.charging.confirmed?'':'warn','energy')}</div><div class="freshness">${icon('clock')}<div>${age(m.updated_time,'车辆数据更新于 ')}<span class="subtle">云端缓存 · 不代表实时状态</span></div></div><button class="closure-summary" data-page="car" aria-label="查看门窗详情">${[['doors','车门'],['windows','车窗'],['trunk','尾门']].map(([key,label])=>`<span class="${closure[key]==='未知'?'unknown':''}">${label}${esc(closure[key])}</span>`).join('')}${icon('arrow')}</button></div><div class="hero-car">${profile.image?`<img src="${esc(profile.image)}" alt="${esc(profile.image_alt)}">`:icon('car')}</div></section>
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
function car() {
  if (!state?.model) return modelRequired();
  const m = state.model;
  const pm25 = m.fields.find(field => field.group === '空气质量' && field.key === 'interiorPM25')?.value;
  const hasPm25 = (typeof pm25 === 'number' || (typeof pm25 === 'string' && pm25.trim() !== '')) && Number.isFinite(Number(pm25)) && Number(pm25) >= 0;
  const positions = ['左前','右前','左后','右后'];
  const doors = positions.map(name => m.doors.find(d => d.name === name) || {name,door:'未知',lock:'未知',window:'未知',raw:{}});
  const labels = [['door','车门'],['lock','门锁'],['window','车窗']];
  const lock = m.lock.confirmed ? m.lock.value : '未知';
  const statuses = doors.flatMap(d => labels.map(([key,label]) => ({name:d.name+label,value:d[key]})))
    .concat([{name:'中控锁',value:lock},{name:'尾门',value:m.trunk},{name:'前舱盖',value:m.hood}]);
  const attention = statuses.filter(item => carStateKind(item.value) === 'attention');
  const unknown = statuses.filter(item => carStateKind(item.value) === 'unknown');
  const doorCards = doors.map((d,i) => `<article class="car-door car-door-${i}" data-position="${d.name}"><h3>${d.name}<span>${['主驾','副驾','后排','后排'][i]}</span></h3>${labels.map(([key,label]) => `<div class="inline-row"><span>${label}</span>${carState(d[key])}</div>`).join('')}</article>`).join('');
  const doorFields = doors.flatMap(d => labels.map(([key,label]) => ({name:d.name+label,value:d.raw?.[key] ?? '未知',evidence:carStateKind(d[key]) === 'unknown' ? '待核实' : '本车已核对'})));
  const climateFields = m.fields.filter(f => f.group === '空调与舒适' && !/^(winPos|winStatus)/.test(f.key) && !['interiorTemp','exteriorTemp','temperatureUpdateTime'].includes(f.key));
  const equipment = f => /sunroof|curtain/i.test(f.key) || /^(rl|rr)Vent/.test(f.key);
  const seat = f => /^(drv|pass|rl|rr|steerWhl)/.test(f.key);
  return `<section class="car-summary" aria-label="车辆状态摘要">
    <div class="car-summary-top"><div class="car-freshness">${icon('clock')}<strong>${age(m.updated_time,'车辆数据更新于 ')}</strong><span>云端缓存 · 不代表实时状态</span></div><div class="car-summary-counts"><span class="car-state state-${attention.length ? 'attention' : 'neutral'}">需关注 ${attention.length} 项</span><span class="car-state state-${unknown.length ? 'unknown' : 'neutral'}">未知 ${unknown.length} 项</span></div></div>
    <div class="car-summary-stats">${labels.map(([key,label]) => { const count = doors.filter(d => carStateKind(d[key]) === 'safe').length; return `<div><span>${label}</span><strong class="state-${count === 4 ? 'safe' : 'unknown'}">${count}<small> / 4</small></strong><span>${key === 'lock' ? '已确认锁止' : '已确认关闭'}</span></div>`; }).join('')}</div>
    ${attention.length ? `<div class="car-attention-list">${attention.map(item => `<span>${esc(item.name)} · ${esc(item.value)}</span>`).join('')}</div>` : ''}
    <p class="car-summary-note">${unknown.length ? '未知项请在下方逐项查看；未知不代表正常或异常。' : '以上为缓存快照中的门窗状态。'}</p>
  </section>
  <div class="car-main-grid"><section class="card car-closures"><div class="card-head"><h2>门锁、车门与车窗</h2><span class="car-caption">左舵车辆 · 只读状态</span></div><div class="card-body">
    <div class="car-vehicle-grid"><div class="car-end car-hood"><span>车头 · 前舱盖</span>${carState(m.hood)}</div>${doorCards}<div class="car-art">${carPhoto()}</div><div class="car-end car-trunk"><span>车尾 · 尾门</span>${carState(m.trunk)}</div></div>
    <div class="car-lock-row"><span>${icon('lock')}中控锁</span>${carState(lock)}</div>
    <p class="car-caption car-legend"><span class="state-safe">关闭 / 锁止</span><span class="state-attention">打开 / 未锁</span><span class="state-unknown">未知</span><span>状态以文字为准</span></p>
  </div></section>
  <div class="car-secondary"><section class="card car-tyres"><div class="card-head"><h2>四轮胎压与胎温</h2><span class="car-caption">车头朝上</span></div><div class="card-body"><div class="tyre-grid car-wheel-grid">${positions.map(name => { const t = m.tyres.find(t => t.name === name); return `<div class="car-wheel" data-position="${name}"><span class="car-wheel-name">${name}</span><strong>${esc(t?.pressure ?? '未知')}</strong><span>胎温 ${esc(t?.temperature ?? '未知')}</span></div>`; }).join('')}</div><p class="car-caption car-tyre-note">保留接口精度；暂无已核对的胎压报警阈值。</p></div></section>
  <section class="card car-cabin"><div class="card-head"><h2>座舱与环境</h2></div><div class="card-body"><div class="temperature"><div><div class="small-label">车内温度</div><div class="temp-value">${esc(m.metrics.inside)}</div></div><div><div class="small-label">车外温度</div><div class="temp-value">${esc(m.metrics.outside)}</div></div></div><div class="car-temperature-time">${icon('clock')}${age(m.temperature_updated_time,'温度更新于 ')}</div><p class="car-caption">温度与整车状态可能不同步</p><div class="car-pm25"><div class="car-pm25-reading"><span class="small-label">车内 PM2.5</span><strong class="car-pm25-value">${hasPm25 ? esc(pm25) : '暂无数据'}</strong></div><p class="car-caption">${hasPm25 ? '单位待核实 · 独立更新时间未提供' : '未返回有效读数'}</p></div></div></section></div></div>
  <section class="card car-data"><div class="card-head"><h2>参数与数据详情</h2>${link('全部参数','fields')}</div><p class="card-meta">按需展开查看。待核实参数不代表本车配备或正在运行该设备。</p>
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
  const electric = m.fields.filter(f => f.group === '能源与充电');
  const field = key => electric.find(f => f.key === key);
  const time = field('timeToFullyCharged');
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
  <section class="charge-history-section" id="charge-history"><div class="charge-history-head"><div><h2>充电记录</h2><p>按结束时间归入北京时间日期，每页显示 20 条。</p></div><label>充电记录日期<input type="date" id="charge-date" value="${esc(chargeDate)}"></label></div><div class="charge-history-layout"><section class="card charge-list-card"><div id="charge-list">${chargeHistoryBody()}</div></section>${chargeDetail(chargeSelected)}</div></section>
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
  const archives = state?.archived_vehicles || [];
  const toolbar = `<div class="track-toolbar"><div class="tabs" aria-label="轨迹来源"><button class="tab ${trackSource==='local'?'active':''}" data-source="local">本地记录</button><button class="tab ${trackSource==='cloud'?'active':''}" data-source="cloud">云端历史</button></div><label><span class="subtle">北京时间 </span><input type="date" id="track-date" aria-label="轨迹日期" value="${esc(trackDate)}"></label></div>`;
  if (trackSource === 'cloud') return toolbar + cloudHistoryPage();
  const note = `<div class="notice info">${icon('info')}本地记录仅覆盖采集开启期间。重复缓存不新增定位，不可信点和较长间断不会连接。</div>`;
  if (!state?.model && !archives.length) return toolbar + note + modelRequired();
  const summaries = `<section class="card event-list-card"><div class="card-head"><h2>已结束行程</h2><span class="subtle">北京时间 · 当前车辆</span></div><div id="event-list">${empty('正在读取行程','从本地事件记录读取，不请求车辆云端。','tracks')}</div></section>`;
  if (!showPosition) return toolbar + note + summaries + `<section class="card section-gap">${privacyGate(true)}</section>`;
  const selector = archives.length ? `<select id="archive-vehicle" class="select" aria-label="已记录车辆"><option value="">${state.model?'当前车辆':'首辆本地车辆'}</option>${archives.map(v=>`<option value="${esc(v.key)}" ${v.key===archiveVehicle?'selected':''}>${esc(v.label)}</option>`).join('')}</select>` : '';
  return toolbar + note + summaries + `<div class="filters">${selector}${action('隐藏位置','hide-position','secondary')}${action('重新查询','reload-tracks','secondary','refresh')}${link('管理采集','settings')}</div><div id="track-content"><section class="card">${empty('正在读取记录','正在查询所选日期。','tracks')}</section></div>`;
}

function monitoringPanel() {
  const monitor = state?.monitoring || {status:'not_started',events:[]};
  const labels = {not_started:'尚未启用',fresh:'获得新数据',unchanged:'等待车辆更新',stale:'车辆缓存过旧',blocked:'需要处理',cooldown:'接口冷却中',retrying:'连接重试中',stopped:'已停止',paused:'已暂停',unavailable:'状态暂不可用'};
  const delivery = {pending:'等待发送',sending:'发送中',sent:'已发送',failed:'发送失败',uncertain:'发送结果待确认'};
  const kinds = {trip_end:'行程总结',charge_start:'开始充电',charge_end:'充电总结'};
  const activity = {waiting:'下电等待 10 分钟',driving:'行程记录中',idle:'暂无进行中的记录',charging:'充电记录中',unknown:'待确认'};
  const label = monitor.status === 'not_started' ? labels.not_started : monitor.online ? labels[monitor.status] || '运行中' : '监控未在线';
  return `<section class="card section-gap"><div class="card-head"><h2>自动行程与充电通知</h2>${pill(label,monitor.online && !['blocked','stale'].includes(monitor.status)?'good':'warn')}</div><div class="card-body"><p class="subtle">后台默认每 60 秒检查，确认停车 10 分钟后降至 300 秒；充电中保持 60 秒。确认下电后等待 10 分钟发送行程总结；充电开始、停止时发送通知。云端数据延迟或缺失时，确认和通知也会延后。</p>${row('行程',activity[monitor.trip] || '待确认')}${row('充电',activity[monitor.charge] || '待确认')}${row('通知渠道','企业微信群机器人')}${monitor.error?`<p class="unknown">${esc(monitor.error)}</p>`:''}<p class="subtle">采集与通知共用一个后台任务。关闭浏览器不停止；下方暂停会同时暂停车辆检查和新事件检测，服务重启后默认恢复。</p>${(monitor.events || []).length?`<h3>最近通知</h3>${monitor.events.map(event=>row(kinds[event.kind] || '通知',delivery[event.delivery] || '未知')).join('')}`:'<p class="subtle">暂无通知记录。</p>'}</div></section>`;
}

function settings() {
  const recording = state?.recording || {active:true,interval:60,last_sample:'未知',last_new:'未知'};
  return `<section class="card"><div class="card-head"><h2>连接与隐私</h2>${pill('Web 服务已连接')}</div><div class="card-body"><div class="settings-row"><div><h3>账号会话</h3><p>${state?.authenticated?'已发现车辆会话；可用性以最近一次车辆读取结果为准。':'尚未登录。请在运行服务的设备上完成车辆登录。'}</p></div>${pill(state?.authenticated?'会话已保存':'未登录',state?.authenticated?'':'warn')}</div><div class="settings-row"><div><h3>位置显示</h3><p>地图及轨迹共用开关。隐藏后清除当前页面的地图与坐标；不会删除已有本地记录或停止采集。</p></div>${action(showPosition?'隐藏位置':'显示位置并加载地图',showPosition?'hide-position':'show-position','secondary')}</div></div></section>${monitoringPanel()}
  <section class="card section-gap"><div class="card-head"><h2>本地轨迹采集</h2>${pill(({active:'采集中',paused:'已暂停',failed:'需要处理',offline:'后台未在线'})[recording.status] || '等待后台',recording.status==='active'?'good':'warn')}</div><div class="card-body"><div class="notice info">${icon('info')}服务启动默认开启；由同一后台保存轨迹并检测行程和充电。暂停会同时停止自动检查与通知处理，已有记录保留。网络故障退避重试；账号失效需更新会话。</div><div class="settings-row"><div><h3>自适应采样</h3><p>默认 60 秒；确认下电、静止且未充电满 10 分钟后降至 300 秒。起步最多延迟约 5 分钟发现，可能缺少开头轨迹。充电或状态不明保持 60 秒。</p></div><div class="settings-control">${action(recording.active?'暂停采集':'开始采集','recording',recording.active?'secondary':'')}</div></div>${row('当前采样间隔', `${recording.effective_interval || 60} 秒`)}${row('最近采样检查',recording.last_sample)}${row('最近新增观测',recording.last_new)}${row('轨迹数据库大小',`${((state?.storage_bytes||0)/1024).toFixed(1)} KB`)}<div class="subtle">数据保存在运行服务的设备上；默认不自动删除历史记录。</div></div></section><section class="card section-gap"><div class="card-head"><h2>关于数据</h2></div><div class="card-body"><p class="subtle">界面依据已核对的字段规则解释车辆数据。社区接口可能变化；字段存在不代表硬件可用，更不代表远程控制已接入。</p>${row('历史轨迹接口',state?.history?.message || '待连接')}${row('Web 连接','当前页面已连接服务')}${row('数据来源','GW2 云端缓存')}</div></section>`;
}

function more() { return `<div class="more-grid">${['energy','fields','settings'].map(key => `<button data-page="${key}">${icon(key)}${pages[key]}${icon('arrow')}</button>`).join('')}</div>`; }

function render() {
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
  const body = {overview,car,energy,map:mapPage,tracks:tracksPage,fields:fieldsPage,settings,more}[page]();
  $('#main').innerHTML = head() + (error ? `<div class="notice error" role="alert">${icon('info')}<p>${esc(error)}${state?.model?' · 下方保留上次读取的数据与原时间。':''}</p></div>` : '') + (['overview','car'].includes(page) && refreshMessage?`<div class="refresh-result" role="status">${esc(refreshMessage)}</div>`:'') + body + (state?.model ? `<div class="status-footer">本次读取 ${esc(state.read_at)} · 车辆状态更新 ${esc(state.model.updated_at)}</div>` : '');
  carOpenDetails.forEach(key => { const detail = $(`details[data-detail="${key}"]`); if(detail) detail.open = true; });
  if (carFocusedDetail) $(`details[data-detail="${carFocusedDetail}"] > summary`)?.focus({preventScroll:true});
  updateClock();
  if (page === 'fields') {renderFields();reviewRestoreFocus(fieldFocus);}
  if (page === 'tracks' && trackSource === 'cloud') renderCloudMap();
  if (page === 'map' && showPosition && state?.model) loadLocation(generation);
  if (page === 'energy' && state?.model) loadChargeEvents(generation);
  if (page === 'tracks' && trackSource === 'local') {
    loadEvents(generation);
    if (showPosition && (state?.model || state?.archived_vehicles?.length)) loadTracks(generation);
  }
}

function createMap(center, zoom = 14, options = {}) {
  if (!window.L) throw Error('地图组件无法加载，请重启本机服务。');
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

async function loadTracks(version) {
  try {
    const result = await api(`/api/tracks?date=${encodeURIComponent(trackDate)}${archiveVehicle?'&vehicle='+encodeURIComponent(archiveVehicle):''}`);
    if (generation !== version || !showPosition) return;
    trackData = result;
    playback = result.observations.filter(point => point.plottable);
    if (!result.count) {
      $('#track-content').innerHTML = `<section class="card">${empty('这一天还没有本地记录',state.recording.active?'采集正在运行，新的缓存观测将在此显示。':'开启采集后，新的位置观测将保存在本机。此前未采集的路段无法补回。','tracks')}<div class="card-meta">${link('前往采集设置','settings')}</div></section>`;
      return;
    }
    $('#track-content').innerHTML = `<div class="map-layout"><section class="card"><div id="map" class="map-canvas" aria-label="本地采样轨迹地图"></div><div id="map-status" class="map-status">${result.count} 条观测 · ${result.segments.length} 个可信片段 · ${result.truncated?'仅显示前 5000 条，请缩小范围':'时间以缓存状态时间为准，缺失时使用本机观测时间'}</div><div class="track-timeline"><div id="playback-label" class="subtle">拖动滑块逐点回看</div><input id="playback" type="range" aria-label="轨迹回看位置" min="0" max="${Math.max(0,playback.length-1)}" value="0" ${playback.length?'':'disabled'}></div></section><section class="card"><div class="card-head"><h2>采样时间线</h2>${pill('本地记录')}</div><div class="point-list">${result.observations.map(point=>`<div class="point"><span>${esc(point.time_label.replace('（北京时间）',''))}<span class="field-path">${esc(point.time_source)}</span></span>${pill(point.trusted?'接口标记可信':'位置未确认',point.trusted?'':'warn')}</div>`).join('')}</div></section></div>`;
    if (!playback.length) { $('#map').innerHTML = empty('没有可绘制的位置','观测已保存，但坐标无效或坐标系尚未适配。','map'); return; }
    createMap([playback[0].latitude,playback[0].longitude],13);
    result.segments.forEach(segment => {
      if (segment.length>1) L.polyline(segment.map(p=>[p.latitude,p.longitude]),{color:'#20776e',weight:4}).addTo(map);
    });
    playback.forEach(point => L.circleMarker([point.latitude,point.longitude],{radius:4,color:point.trusted?'#20776e':'#9aa4a2',fillOpacity:.7,weight:1}).addTo(map));
    if (playback.length>1) map.fitBounds(playback.map(p=>[p.latitude,p.longitude]),{padding:[30,30],maxZoom:16});
    setPlayback(0);
  } catch (error) {
    if (generation === version) $('#track-content').innerHTML = `<section class="card">${empty('记录读取失败',error.message,'tracks')}</section>`;
  }
}

async function loadEvents(version) {
  const request = ++eventRequest;
  try {
    const result = await api(`/api/events?date=${encodeURIComponent(trackDate)}&kind=trip_end${eventCursor?`&cursor=${encodeURIComponent(eventCursor)}`:''}`);
    if (request !== eventRequest || generation !== version || trackSource !== 'local' || !$('#event-list')) return;
    if (!result.events.length) {
      $('#event-list').innerHTML = empty('这一天没有已结束行程','本地记录为空；部分或尚未确认结束的行程不会列入。','tracks');
      return;
    }
    $('#event-list').innerHTML = `<div class="event-rows">${result.events.map(event => `<article class="event-row"><div><strong>${esc(new Date(event.end_time).toLocaleString('zh-CN',{hour12:false}))}</strong><span>${event.partial?'部分记录':'完整记录'}</span></div><div><b>${Number.isFinite(event.distance_km)?`${esc(event.distance_km)} km`:'里程未知'}</b><span>${Number.isFinite(event.start_soc)?`${esc(event.start_soc)}%`:'未知'} 至 ${Number.isFinite(event.end_soc)?`${esc(event.end_soc)}%`:'未知'}</span></div></article>`).join('')}</div><div class="event-pagination"><button class="button secondary" data-action="events-prev" ${eventCursorStack.length?'':'disabled'}>上一页</button><button class="button secondary" data-action="events-next" data-cursor="${esc(result.next_cursor || '')}" ${result.next_cursor?'':'disabled'}>下一页</button></div>`;
  } catch (error) {
    if (generation === version && $('#event-list')) $('#event-list').innerHTML = empty('行程摘要读取失败',error.message,'tracks');
  }
}

function setPlayback(index) {
  const point = playback[index];
  if (!point || !map) return;
  if (mapMarker) mapMarker.remove();
  mapMarker = L.circleMarker([point.latitude,point.longitude],{radius:9,color:point.trusted?'#20776e':'#8a9391',fillOpacity:.35,weight:3}).addTo(map);
  map.panTo([point.latitude,point.longitude],{animate:trackSource!=='cloud'});
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

async function toggleRecording() {
  if (busy) return;
  const interval = Number($('#interval')?.value || state.recording.interval);
  if (!Number.isInteger(interval) || interval<60 || interval>3600) { toast('采样间隔须为 60–3600 秒的整数。'); return; }
  busy=true;
  try {
    state = await api('/api/recording',{active:!state.recording.active,interval});
    transientError='';
    toast(state.recording.active?'已启用统一采集，请查看后台运行状态。':'自动采集与通知检测已暂停，已有记录保留。');
  } catch(error) { transientError=error.message; }
  finally { busy=false;render(); }
}

document.addEventListener('click', event => {
  const target = event.target.closest('button');
  if (!target || target.disabled) return;
  if (handleReviewAction(target)) return;
  if (handleCloudAction(target)) return;
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
    case 'events-next': if(target.dataset.cursor){eventCursorStack.push(eventCursor);eventCursor=target.dataset.cursor;render();}break;
    case 'events-prev': if(eventCursorStack.length){eventCursor=eventCursorStack.pop();render();}break;
    case 'charge-select': chargeSelected=chargeEvents.find(item=>item.id===target.dataset.eventId)||chargeSelected;renderChargeHistory();break;
    case 'charge-next': if(chargeNextCursor){chargeCursorStack.push(chargeCursor);chargeCursor=chargeNextCursor;chargeSelected=null;loadChargeEvents(generation);}break;
    case 'charge-prev': if(chargeCursorStack.length){chargeCursor=chargeCursorStack.pop();chargeSelected=null;loadChargeEvents(generation);}break;
    case 'charge-retry': loadChargeEvents(generation);break;
    case 'charge-latest': chargeDate=beijingDate(Number.isFinite(state?.recent_events?.charge_end?.end_time)?state.recent_events.charge_end.end_time:Date.now());chargeCursor=null;chargeCursorStack=[];chargeSelected=null;chargeEvents=[];render();break;
    case 'recording': toggleRecording();break;
  }
});
document.addEventListener('input', event => {
  if(event.target.id==='search') {search=event.target.value;renderFields();}
  if(event.target.id==='playback') setPlayback(Number(event.target.value));
});
document.addEventListener('change', event => {
  if(event.target.id==='group') {groupFilter=event.target.value;renderFields();}
  if(event.target.id==='unknown') {unknownOnly=event.target.checked;renderFields();}
  if(event.target.id==='track-date') {trackDate=event.target.value;eventCursor=null;eventCursorStack=[];render();}
  if(event.target.id==='charge-date') {chargeDate=event.target.value;chargeCursor=null;chargeCursorStack=[];chargeSelected=null;chargeEvents=[];render();}
  if(event.target.id==='archive-vehicle') {archiveVehicle=event.target.value;render();}
  if(event.target.id==='vehicle-select') {chargeDateInitialized=false;chargeCursor=null;chargeCursorStack=[];chargeSelected=null;chargeEvents=[];refresh();}
});

async function pollState(force = false) {
  if(polling || busy || (!force && document.hidden)) return;
  polling=true;
  try {
    const latest=await api('/api/state',undefined,8000);
    const changed=!state || latest.read_time!==state.read_time || latest.error!==state.error ||
      latest.recording.effective_interval!==state.recording.effective_interval || latest.recording.status!==state.recording.status || latest.recording.last_new!==state.recording.last_new ||
      latest.recording.last_sample!==state.recording.last_sample || latest.next_query_at!==state.next_query_at ||
      latest.request_key!==state.request_key || latest.vehicle!==state.vehicle ||
      JSON.stringify(latest.history)!==JSON.stringify(state.history) ||
      latest.snapshot_revision!==state.snapshot_revision ||
      JSON.stringify(latest.recent_events)!==JSON.stringify(state.recent_events) ||
      JSON.stringify(latest.field_reviews)!==JSON.stringify(state.field_reviews);
    const restarted=state && latest.request_key!==state.request_key;
    state=latest; connectionFailures=0;
    if(restarted) { transientError='';refreshMessage=''; }
    if(changed) render();
    else { updateConnection();updateClock(); }
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
