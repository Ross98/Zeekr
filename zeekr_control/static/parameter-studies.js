(function(root){'use strict';
const stages={cross_checked:'专门跨字段对照',scenario_only:'场景对照，仍是候选',constant_only:'单一值，缺少变化',no_data:'本期未取得有效值',existing_interpretation:'已有部分解释'};
const names={pairs:'同快照对照数',spread:'关系差值变化范围',anchor_span:'参考里程变化',samples:'有效样本',calendar_days:'日历经过天数',decrease:'计数下降量',distinct:'不同原值数',charge_negative:'充电期负电流',charge_positive:'充电期正电流',trip_positive:'行程期正电流',trip_negative:'行程期负电流',paired_charge:'桩侧/电池侧匹配数',ratio_median:'电流绝对值比中位数',timestamp_changes:'停车时间码变化次数',near_power_off:'接近动力关闭边界',near_p_gear:'接近P档边界',paired_motion:'可信运动片段数',median_angle_error:'0北顺时针角误差中位数（度）',best_offset:'最佳角度偏移（度）',min:'最小原值',max:'最大原值',over_100:'原值超过100',off_samples:'同组状态0/2下样本',reset_windows:'小计归零窗口',low_voltage_zero_soc:'低压读数小于8且SOC为0'};
function render(row,esc,num){
  const s=row.study;if(!s)return '';const ev=s.cross_evidence||{};
  return `<section class="hypothesis-study"><strong>${esc(stages[s.stage])}</strong><p>${esc(s.definition)}</p>${row.current_reference?`<p class="insight-note">当前资料参考：${esc(row.current_reference.value)} · 原值 ${esc(row.current_reference.raw)} · ${esc(row.current_reference.scope)}</p>`:''}${row.presence?`<p class="insight-note">可解析原值 ${row.presence.valid} · 返回空值 ${row.presence.empty} · 未返回 ${row.presence.missing} · 格式无效 ${row.presence.invalid}。</p>`:''}<p class="insight-note">论证方式：${esc(s.test)}</p>${Object.keys(ev).length?`<details><summary>查看专门对照证据</summary>${ev.joint?`<p>对照：${esc(ev.anchor)}</p><table><thead><tr><th>本字段</th><th>对照原值/状态</th><th>次数</th></tr></thead><tbody>${ev.joint.map(v=>`<tr><td>${esc(v.value)}</td><td>${esc(v.anchor)}</td><td>${v.count}</td></tr>`).join('')}</tbody></table>`:''}${Object.entries(ev).filter(([k,v])=>names[k]&&typeof v==='number').map(([k,v])=>`<p class="insight-note">${esc(names[k])}：${num(v)}</p>`).join('')}${ev.returned_while_off?`<p class="insight-note">同组状态0/2时仍返回的设定码：${esc(JSON.stringify(ev.returned_while_off))}</p>`:''}</details>`:''}<p class="insight-note">同快照共同返回，不保证子系统更新时间相同；交叉支持不替代实车操作核实。</p></section>`;
}
function markdown(data,label){
  const clean=v=>String(v??'').replace(/\|/g,'\\|').replace(/\n/g,' ');
  const lines=['# 全部公开参数逐项研究',`范围：${data.start_date} 至 ${data.end_date}；对照：${label}`,`公开目录 ${data.catalog} 项，本次候选 ${data.candidates.length} 项；自选对照参数自身排除候选。`,'','专门对照不等于实车确认；常量、未返回和通用规则不算已解释完成。','','| 参数 | 路径 | 阶段 | 数据/当前资料 | 含义/候选 | 已出现值解释 | 下一步论证 |','|---|---|---|---|---|---|---|'];
  for(const r of data.candidates){
    const meanings=(r.proposal.value_meanings||[]).map(v=>`${v.raw}=${v.meaning}（${v.source}）`).join('；')||r.proposal.meaning;
    lines.push('| '+[r.name,r.path,stages[r.study?.stage]||'待登记',r.presence?`有值${r.presence.valid}，空值${r.presence.empty}，未返回${r.presence.missing}，格式无效${r.presence.invalid}${r.current_reference?'；当前资料：'+r.current_reference.value:''}`:'',r.study?.definition||'',meanings+(r.other_values?`；另有${r.other_values}种原值未逐个列出，按本字段数值规则解释`:''),r.study?.test||r.proposal.next].map(clean).join(' | ')+' |');
  }
  lines.push('','## 专门对照与反例','以下反例以本次所选场景为基准；不代表所有参数应随该场景同步变化。');
  for(const r of data.candidates){
    lines.push('',`### ${r.name} · ${r.path}`,r.proposal.basis||'',`专门证据：${JSON.stringify(r.study?.cross_evidence||{})}`,`两种反例：状态变参数不变 ${r.transitions.state_only} 次；参数变状态不变 ${r.transitions.field_only} 次；长缺口 ${r.transitions.gaps} 次。`);
  }
  return lines.join('\n');
}
function download(data,label){
  const url=URL.createObjectURL(new Blob([markdown(data,label)],{type:'text/markdown;charset=utf-8'})),a=document.createElement('a');
  a.href=url;a.download='参数逐项研究-'+data.end_date+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
root.ParameterStudies={stages,render,markdown,download};
})(window);
