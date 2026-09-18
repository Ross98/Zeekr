/* Manual vehicle-specific annotations. These never change the vehicle decoder. */
const reviewLabels = {pending:'待核实', partial:'部分确认', confirmed:'已确认', question:'有疑问', na:'不适用'};
let reviewFilter = '', reviewSelected = '', reviewVehicle = null, reviewSaving = false, reviewUndo = null;
let reviewEditing = false;
const reviewDrafts = new Map();

function reviewData() { return state?.field_reviews || {vehicle:null,revision:null,records:[]}; }
function reviewRecords(path) { return reviewData().records.filter(record => record.path === path); }
function reviewMatch(field, scope = null) {
  const records = reviewRecords(field.path);
  if (scope) return records.find(r => r.scope === scope && (scope === 'field' || r.raw === field.raw));
  return records.find(r => r.scope === 'field' && r.status === 'na') ||
    records.find(r => r.scope === 'value' && r.raw === field.raw) || records.find(r => r.scope === 'field');
}
function reviewStatus(field) {
  const record = reviewMatch(field);
  if (record) return record.status;
  if (field.reference?.kind === 'number' && reviewRecords(field.path).some(r => r.status === 'confirmed')) return 'confirmed';
  return reviewRecords(field.path).length ? 'partial' : 'pending';
}
function reviewDraftKey(path) { return JSON.stringify([reviewVehicle,path]); }
function reviewDraft() { return reviewDrafts.get(reviewDraftKey(reviewSelected)); }
function reviewSync() {
  if (reviewVehicle !== reviewData().vehicle) {
    reviewVehicle = reviewData().vehicle;
    reviewSelected = '';
    reviewUndo = null;
    reviewEditing = false;
  }
}
function newReviewDraft(field, scope = null) {
  const record = reviewMatch(field, scope);
  return {path:field.path, raw:field.raw, scope:scope || record?.scope || 'value',
    status:'confirmed', meaning:'', unit:'', conversion:'', observation:'', scene:'', note:'',
    observed_at:state.model.updated_time ?? null, ...record,
    // Numeric rules retain their old observation until the user chooses a new snapshot.
    dirty:false, saved:false, revision:reviewData().revision};
}
function reviewVisibleFields() {
  return (state?.model?.fields || []).filter(f => f.evidence !== '未知' && f.value !== '未知' && f.raw !== '未知');
}
function reviewItems() {
  return reviewVisibleFields().filter(f => (!groupFilter || f.group === groupFilter) &&
    (!unknownOnly || f.evidence === '待核实') && (!reviewFilter || reviewStatus(f) === reviewFilter) &&
    `${f.name} ${f.path} ${f.reference?.unit || ''} ${f.reference?.note || ''} ${f.reference?.applicability || ''}`.toLowerCase().includes(search.toLowerCase()))
    .sort((a,b) => Number(reviewStatus(a) !== 'pending') - Number(reviewStatus(b) !== 'pending'));
}
function fieldsPage() {
  if (!state?.model) return modelRequired();
  reviewSync();
  const groups = [...new Set(reviewVisibleFields().map(f => f.group))];
  return `<div class="review-intro"><p>浏览中文术语、当前值、单位与来源；需要时再编辑人工核实。</p><span class="pill">只读车辆 · 核实记录独立</span></div>
    ${state.profile?.variant ? `<p class="section-note">本车资料：${esc(state.profile.name)} · ${esc(state.profile.variant)}</p>` : ''}
    <div id="review-progress" class="review-progress" aria-label="人工核实进度"></div>
    <div class="filters"><input type="search" id="search" aria-label="搜索参数" placeholder="搜索中文名称或字段，如：胎压、chargeLevel" value="${esc(search)}"><select class="select" id="group" aria-label="参数分类"><option value="">全部分类</option>${groups.map(g => `<option ${groupFilter===g?'selected':''}>${esc(g)}</option>`).join('')}</select><label class="check"><input type="checkbox" id="unknown" ${unknownOnly?'checked':''}>仅系统待核实</label></div>
    <p class="section-note">未核实参数也可正常读取、展示和参考；标记仅说明解释尚未确认。枚举按具体原值核实，未知项已隐藏（${state.model.fields.length-reviewVisibleFields().length} 项）；有效值返回后恢复展示。</p>
    ${reviewData().error ? `<div class="notice error" role="alert">${esc(reviewData().error)}</div>` : ''}
    <div class="review-workspace"><section class="card review-list" id="field-results"></section><aside class="card review-panel" id="review-panel" aria-label="参数核实面板"></aside></div>`;
}
function renderFields() {
  if (!$('#field-results')) return;
  reviewSync();
  const focus = reviewFocusSnapshot();
  const all = reviewVisibleFields(), items = reviewItems();
  if (!all.some(f => f.path === reviewSelected)) reviewSelected = '';
  const counts = Object.fromEntries(Object.keys(reviewLabels).map(key => [key,all.filter(f => reviewStatus(f) === key).length]));
  $('#review-progress').innerHTML = [['','全部',all.length],...Object.entries(reviewLabels).map(([key,label])=>[key,label,counts[key]])].map(([key,label,count]) =>
    `<button class="review-count ${reviewFilter===key?'active':''}" data-review-filter="${key}" aria-pressed="${reviewFilter===key}"><span>${label}</span><strong>${count}</strong></button>`).join('');
  if (!reviewSelected && items.length) reviewSelected = items[0].path;
  $('#field-results').innerHTML = `<div class="card-head"><h2>参数清单</h2><span class="subtle">${items.length} 项 · 待核实优先</span></div><div class="review-rows">${items.length ? items.map(f => {
    const status = reviewStatus(f), record = reviewMatch(f);
    return `<button class="review-row ${reviewSelected===f.path?'selected':''}" data-review-path="${esc(f.path)}" aria-pressed="${reviewSelected===f.path}"><span class="review-row-title"><strong>${esc(f.name)}</strong><span class="pill ${status==='confirmed'?'good':status==='pending'||status==='question'?'warn':''}">${reviewLabels[status]}</span></span><span class="field-path">${esc(f.group)} · ${esc(f.path)}</span><span class="review-values"><span>原值 <b>${esc(f.raw)}</b></span><span>${record?.status==='confirmed'?'人工解释':'系统解释'} <b>${esc(record?.status==='confirmed'?record.meaning:f.value)}</b></span></span></button>`;
  }).join('') : '<div class="empty"><h3>没有符合条件的参数</h3><p>调整搜索、分类或核实状态。</p></div>'}</div>`;
  renderReviewPanel();
  reviewRestoreFocus(focus);
}
function reviewTime(value) { return Number.isFinite(value) ? new Date(value).toLocaleString('zh-CN',{hour12:false}) : '未提供'; }
function renderFieldReference(field) {
  const ref = field.reference;
  if (!ref) return '';
  const sources = (ref.sources || []).filter(source => {
    try { return new URL(source.url).protocol === 'https:'; } catch { return false; }
  });
  return `<section class="field-reference" aria-label="词典参考"><h3>词典参考</h3>
    <p><b>单位：</b>${esc(ref.unit || '—')}</p><p><b>术语依据：</b>${esc(ref.basis)}</p>
    <p><b>车型／配置适用性：</b>${esc(ref.applicability || '需核对本车配置')}</p>
    ${ref.applicability_scope ? `<small>${esc(ref.applicability_scope)}</small>` : ''}
    <p>${esc(ref.note)}</p>${sources.length ? `<p class="field-reference-links">${sources.map(source => `<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.title)}</a>`).join(' · ')}</p>` : ''}
    <small>术语推测不等于状态码已确认；以当前原值和人工核实记录为准。</small></section>`;
}
function reviewInput(label, key, value, limit, multiline = false) {
  return `<div class="review-input"><label for="review-${key}">${label}</label>${multiline ? `<textarea rows="2"` : '<input type="text"'} id="review-${key}" data-review-input="${key}" maxlength="${limit}" ${multiline?'':`value="${esc(value)}"`}>${multiline?`${esc(value)}</textarea>`:''}</div>`;
}
function renderReviewPanel() {
  const panel = $('#review-panel');
  if (!panel) return;
  const field = reviewVisibleFields().find(f => f.path === reviewSelected);
  if (!field) { panel.innerHTML = empty('选择一项参数','从左侧清单开始逐项核实。'); return; }
  if (!reviewEditing) {
    const records = reviewRecords(field.path), status = reviewStatus(field);
    panel.innerHTML = `<div class="card-head"><div><span class="eyebrow">参数详情</span><h2>${esc(field.name)}</h2></div><span class="pill ${status==='confirmed'?'good':status==='pending'||status==='question'?'warn':''}">${reviewLabels[status]}</span></div>
      <div class="review-panel-body"><span class="field-path review-path">${esc(field.path)}</span><div class="review-snapshot"><div><span>当前原值</span><strong>${esc(field.raw)}</strong></div><div><span>系统解释</span><b>${esc(field.value)}</b><small>${esc(field.evidence)}</small></div></div>${renderFieldReference(field)}
      <details class="review-history" ${records.length?'open':''}><summary>人工核实记录 · ${records.length} 条</summary>${records.length?records.map(record=>`<div class="review-history-row"><span>${record.scope==='field'?'整个字段':`原值 ${esc(record.raw)}`} · ${reviewLabels[record.status]}</span><strong>${esc(record.meaning || record.note || '未填写说明')}</strong><small>${esc(reviewTime(record.saved_at))}</small></div>`).join(''):'<p class="subtle">暂无人工核实记录。</p>'}</details></div>
      <div class="review-panel-footer"><div class="review-actions"><button type="button" class="button" data-review-action="edit">编辑核实</button></div></div>`;
    return;
  }
  if (!reviewDraft()) reviewDrafts.set(reviewDraftKey(field.path),newReviewDraft(field));
  const scroll = panel.dataset.path === field.path ? panel.querySelector('.review-panel-body')?.scrollTop || 0 : 0;
  panel.dataset.path = field.path;
  const draft = reviewDraft(), records = reviewRecords(field.path);
  const changed = draft.raw !== field.raw;
  const matched = reviewMatch(draft,draft.scope);
  const disabled = reviewSaving || !!reviewData().error || reviewData().revision === null;
  panel.innerHTML = `<div class="card-head"><div><span class="eyebrow">逐项核实</span><h2>${esc(field.name)}</h2></div><span id="review-save-status" class="subtle" role="status">${draft.dirty?'有未保存内容':draft.saved?'已保存':'待填写 / 可修改'}</span></div>
    <div class="review-panel-body"><span class="field-path review-path">${esc(field.path)}</span>
    <div class="review-snapshot"><div><span>本次核实原值</span><strong>${esc(draft.raw)}</strong></div><div><span>系统当前解释</span><b>${esc(field.value)}</b><small>${esc(field.evidence)}</small></div></div>
    ${renderFieldReference(field)}
    <p class="subtle">核实样本时间：${esc(reviewTime(draft.observed_at))}<br>整车缓存时间；子字段可能不同步。</p>
    <div id="review-live-notice" class="${changed?'notice info':'subtle'}">${changed?`当前原值已变化为 ${esc(field.raw)}；填写内容仍对应原值 ${esc(draft.raw)}。`:'填写期间保留本次样本，刷新不会覆盖草稿。'}</div>
    ${changed?'<button class="text-link" data-review-action="latest">使用最新值核实</button>':''}
    <form id="review-form"><fieldset ${reviewSaving?'disabled':''}>
    ${reviewInput('确认含义','meaning',draft.meaning,200)}
    <div class="review-input"><label for="review-scope">核实范围</label><select id="review-scope" data-review-input="scope" class="select"><option value="value" ${draft.scope==='value'?'selected':''}>当前原值的含义（枚举 / 状态）</option><option value="field" ${draft.scope==='field'?'selected':''}>整个字段（数值含义、单位 / 不适用）</option></select></div>
    <p class="review-help">${draft.scope==='value'?`仅记录「${esc(draft.raw)}」的含义，其他原值不自动确认。`:'仅用于数值参数含义与单位，或整个字段不适用。数字编码也可能是枚举，请勿因此确认所有档位。'}</p>
    <div class="review-input"><label for="review-status">核实结果</label><select id="review-status" data-review-input="status" class="select">${['confirmed','question','na'].map(key=>`<option value="${key}" ${draft.status===key?'selected':''}>${reviewLabels[key]}</option>`).join('')}</select></div>

    <div class="review-form-pair">${reviewInput('单位（可选）','unit',draft.unit,40)}${reviewInput('换算方式（仅记录，不执行）','conversion',draft.conversion,200)}</div>
    ${reviewInput('实际观察','observation',draft.observation,600,true)}
    ${reviewInput('核实场景','scene',draft.scene,200)}
    ${reviewInput('备注','note',draft.note,1200,true)}
    <div class="review-quick"><button type="button" class="text-link" data-review-action="question">标记有疑问</button><button type="button" class="text-link" data-review-action="na">本字段不适用</button></div>
    </fieldset><div id="review-error" class="review-error" role="alert"></div>
    </form>
    <details class="review-history" ${records.length?'open':''}><summary>已保存的核实记录 · ${records.length} 条</summary>${records.map((record,index)=>`<button class="review-history-row" data-review-record="${index}" ${reviewSaving?'disabled':''}><span>${record.scope==='field'?'整个字段':`原值 ${esc(record.raw)}`} · ${reviewLabels[record.status]}</span><strong>${esc(record.meaning || record.note || '未填写说明')}</strong><small>${esc(reviewTime(record.saved_at))} · 查看 / 修改</small></button>`).join('')}</details>
    <p class="review-help">确认只保存网页注释，不向车辆下发指令。未核实参数可继续使用；车辆判断与通知仍沿用现有规则。</p></div><div class="review-panel-footer">    <div class="review-actions"><button type="submit" form="review-form" class="button" ${disabled?'disabled':''}>保存并下一项</button><button type="button" class="button secondary" data-review-action="save" ${disabled?'disabled':''}>保存</button><button type="button" class="button quiet" data-review-action="skip" ${reviewSaving?'disabled':''}>暂时跳过</button></div>
    <div class="review-secondary"><button type="button" class="text-link" data-review-action="clear" ${disabled||!matched?'disabled':''}>清除本条确认</button><button type="button" class="text-link" data-review-action="discard" ${reviewSaving||!draft.dirty?'disabled':''}>放弃草稿</button><button type="button" class="text-link" data-review-action="undo" ${disabled||!reviewUndo?'disabled':''}>撤销上次操作</button></div>
</div>`;
  panel.querySelector('.review-panel-body').scrollTop = scroll;
}
function reviewFocusSnapshot() {
  const el = document.activeElement, panel = $('#review-panel');
  if (!panel) return null;
  const input = el?.matches('[data-review-input]');
  return {id:input?el.id:null, start:input?el.selectionStart:null, end:input?el.selectionEnd:null,
    vehicle:reviewVehicle, path:panel.dataset.path, inputTop:input?el.getBoundingClientRect().top:null,
    panelScroll:panel.querySelector('.review-panel-body')?.scrollTop || 0,
    listScroll:document.querySelector('.review-rows')?.scrollTop || 0};
}
function reviewRestoreFocus(focus) {
  if (!focus || focus.vehicle !== reviewVehicle || focus.path !== reviewSelected) return;
  const el = focus.id ? document.getElementById(focus.id) : null;
  el?.focus({preventScroll:true});
  if (el && focus.start !== null && ['INPUT','TEXTAREA'].includes(el.tagName)) el.setSelectionRange(focus.start,focus.end);
  const panel = document.querySelector('.review-panel-body'), list = document.querySelector('.review-rows');
  if (panel) {
    panel.scrollTop = focus.panelScroll;
    if (el && focus.inputTop !== null) panel.scrollTop += el.getBoundingClientRect().top - focus.inputTop;
  }
  if (list) list.scrollTop = focus.listScroll;
}
function reviewNext(items, path) {
  const index = items.findIndex(f => f.path === path);
  const next = items.slice(index+1).concat(items.slice(0,index)).find(f => f.path !== path);
  if (next) reviewSelected = next.path;
}
async function saveReview(action = 'save', next = false, override = null) {
  if (reviewSaving || !reviewDraft()) return;
  const draft = reviewDraft(), vehicle = reviewVehicle;
  const snapshot = {...draft}, items = reviewItems();
  const payload = override || {...snapshot,action,vehicle,revision:draft.revision};
  if (payload.action === 'save' && payload.status === 'confirmed' && !payload.meaning.trim()) {
    $('#review-error').textContent = '请填写确认含义，再保存。'; $('#review-meaning').focus(); return;
  }
  const previous = reviewRecords(payload.path).find(r => r.scope===payload.scope && (r.scope==='field'||r.raw===payload.raw));
  reviewSaving = true; renderReviewPanel();
  try {
    const result = await api('/api/field-reviews',payload);
    if (reviewData().vehicle !== vehicle) return;
    state.field_reviews = result;
    reviewUndo = override ? null : {vehicle,revision:result.revision,action:previous?'save':'delete',...(previous || payload)};
    if (reviewUndo) {reviewUndo.action=previous?'save':'delete';reviewUndo.revision=result.revision;}
    // Update clean drafts only; a dirty draft remains protected against concurrent edits.
    for (const [key,value] of reviewDrafts) {
      if (key.startsWith(JSON.stringify([vehicle]).slice(0,-1)+',') && !value.dirty) value.revision = result.revision;
    }
    const field = state.model.fields.find(f => f.path === payload.path);
    const saved = newReviewDraft({...field,raw:payload.raw},payload.scope);
    saved.saved = true;
    reviewDrafts.set(reviewDraftKey(payload.path),saved);
    toast(override?'已撤销上次操作':action==='delete'?'已清除本条确认':'已保存核实记录');
    if (next) reviewNext(items,payload.path);
    renderFields();
  } catch (error) {
    // Reload metadata after a conflict without discarding the user's input.
    try {
      const latest = await api('/api/state',undefined,8000);
      if (latest.field_reviews?.vehicle === vehicle) {
        state.field_reviews=latest.field_reviews;
        draft.revision=latest.field_reviews.revision;
      }
    } catch { /* Keep the old revision and draft; another save remains guarded. */ }
    renderFields();
    if ($('#review-error')) $('#review-error').textContent=error.message;
    toast(error.message);
  } finally {
    reviewSaving=false;
    // Enable controls without replacing error text or the edited draft.
    const error = $('#review-error')?.textContent;
    renderReviewPanel();
    if(error && $('#review-error')) $('#review-error').textContent=error;
  }
}
function handleReviewAction(target) {
  if (page !== 'fields') return false;
  if (target.hasAttribute('data-review-filter')) {
    reviewFilter=target.dataset.reviewFilter; renderFields(); return true;
  }
  if (target.dataset.reviewPath) {
    if (!reviewSaving) {reviewSelected=target.dataset.reviewPath;renderFields();}
    return true;
  }
  const operation = target.dataset.reviewAction;
  if (!operation && !target.hasAttribute('data-review-record')) return false;
  if (reviewSaving) return true;
  if (operation === 'edit') {reviewEditing=true;renderReviewPanel();return true;}
  const draft = reviewDraft(), field = state.model.fields.find(f=>f.path===reviewSelected);
  if (target.hasAttribute('data-review-record') || operation === 'latest') {
    if (draft.dirty) {toast('请先保存或放弃当前草稿，再切换核实样本。');return true;}
    const record = target.hasAttribute('data-review-record') ? reviewRecords(reviewSelected)[Number(target.dataset.reviewRecord)] : null;
    const fresh = record ? newReviewDraft({...field,raw:record.raw},record.scope) : {...newReviewDraft(field,'value'),raw:field.raw,observed_at:state.model.updated_time};
    reviewDrafts.set(reviewDraftKey(reviewSelected),fresh); renderReviewPanel(); return true;
  }
  if (operation==='save') saveReview();
  if (operation==='clear') saveReview('delete');
  if (operation==='undo' && reviewUndo) saveReview('save',false,reviewUndo);
  if (operation==='skip') {reviewNext(reviewItems(),reviewSelected);renderFields();}
  if (operation==='discard') {reviewDrafts.set(reviewDraftKey(reviewSelected),newReviewDraft({...field,raw:draft.raw},draft.scope));renderReviewPanel();}
  if (operation==='question' || operation==='na') {
    draft.status=operation; if(operation==='na') draft.scope='field'; draft.dirty=true; saveReview();
  }
  return true;
}
document.addEventListener('input', event => {
  const key=event.target.dataset.reviewInput;
  if (!key || !reviewDraft()) return;
  const draft=reviewDraft(); draft[key]=event.target.value; draft.dirty=true;draft.saved=false;
  if ($('#review-save-status')) $('#review-save-status').textContent='有未保存内容';
  const discard=document.querySelector('[data-review-action="discard"]'); if(discard) discard.disabled=false;
});
document.addEventListener('change', event => {
  if (event.target.dataset.reviewInput==='scope') {
    const focus=reviewFocusSnapshot(); renderReviewPanel(); reviewRestoreFocus(focus);
  }
});
document.addEventListener('submit', event => {
  if(event.target.id==='review-form') {event.preventDefault();saveReview('save',true);}
});
