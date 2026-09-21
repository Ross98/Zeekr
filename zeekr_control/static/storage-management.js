/* Server-only archive administration. Never requests vehicle data. */
window.StorageManagement = (() => {
  let panel, request, status, inventory, plan, busy=false, error='', message='', draft='', sequence=0, loadedAt=0;
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const bytes=value=>{
    if(!Number.isFinite(value))return '未知';
    const magnitude=Math.abs(value),unit=magnitude>=1024**3?3:magnitude>=1024**2?2:magnitude>=1024?1:0;
    return `${(value/1024**unit).toFixed(unit?2:0)} ${['B','KiB','MiB','GiB'][unit]}`;
  };
  const date=value=>Number.isFinite(value)?new Date(value*1000).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}):'尚无记录';
  const label={healthy:'正常',warning:'容量提醒',critical:'容量严重不足',unknown:'巡检异常',not_checked:'待首次巡检'};
  const delivery={none:'尚无预警',sending:'发送中',sent:'已发送',uncertain:'发送结果待确认',failed:'发送失败'};
  const button=(text,action,target='',disabled=false,danger=false)=>`<button type="button" class="button ${danger?'storage-danger':'secondary'}" data-storage-action="${action}" data-target="${escape(target)}" ${disabled?'disabled':''}>${text}</button>`;
  function list(items,recycled){
    if(!items.length)return `<p class="subtle">${recycled?'回收区为空。':'尚无完整快照归档。'}</p>`;
    return items.map(item=>`<article class="storage-archive-row"><div><strong>${escape(item.partition)}</strong><p>${bytes(item.bytes)} · ${Number.isFinite(item.reads)?`${item.reads} 次读取`:'记录数未知'}${item.manageable?'':' · 受保护 / 暂不可操作'}</p></div><div class="storage-actions">${recycled?button('恢复','restore',item.id,!item.manageable||busy)+button('永久删除','purge',item.id,!item.manageable||busy,true):button('移入回收区','trash',item.id,!item.manageable||busy)}</div></article>`).join('');
  }
  function draw(){
    if(!panel)return;
    const c=status?.current,m=status?.monitor;
    panel.innerHTML=`<div class="card-head"><div><h2>服务器存储与归档管理</h2><p class="card-meta">服务所在磁盘 · 本地巡检，不读取车辆云端</p></div>${button('刷新存储状态','reload','',busy)}</div><div class="card-body">
      ${error?`<div class="notice error" role="alert">${escape(error)}</div>`:''}${message?`<div class="notice info" role="status">${escape(message)}</div>`:''}
      ${c?`<div class="storage-health-heading"><strong class="${c.status==='healthy'?'':'storage-warning'}">${label[c.status]||'未知'}</strong><span class="subtle">测量于 ${date(c.checked_at)}</span></div><div class="storage-metrics"><div><span>磁盘已用</span><strong>${Number.isFinite(c.disk_used_percent)?c.disk_used_percent.toFixed(1)+'%':'未知'}</strong><small>${bytes(c.disk_used_bytes)} / ${bytes(c.disk_total_bytes)}</small></div><div><span>磁盘剩余</span><strong>${bytes(c.disk_free_bytes)}</strong><small>同盘其他程序也占用空间</small></div><div><span>车辆数据目录</span><strong>${bytes(c.data_bytes)}</strong><small>完整归档 ${bytes(c.archive_bytes)}</small></div><div><span>回收区占用</span><strong>${bytes(c.trash_bytes)}</strong><small>移入回收区不释放空间</small></div></div>
      <div class="storage-progress" role="meter" aria-label="磁盘使用率" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.min(100,Math.max(0,c.disk_used_percent||0))}"><span style="width:${Math.min(100,Math.max(0,c.disk_used_percent||0))}%"></span></div>
      <div class="storage-observations"><p>inode 使用：${Number.isFinite(c.inode_used_percent)?c.inode_used_percent.toFixed(1)+'%':'不支持 / 未知'}</p><p>数据日净增长：${Number.isFinite(m?.data_growth_bytes_per_day)?bytes(m.data_growth_bytes_per_day)+'/天':'至少 6 小时样本后估算'}</p><p>预计磁盘剩余天数：${Number.isFinite(m?.estimated_disk_days)?m.estimated_disk_days.toFixed(1)+' 天（按同盘净增长）':'样本不足或没有净增长'}</p><p>后台巡检：${date(m?.checked_at)}${m?.monitor_fresh?'':' · 尚未更新，请检查后台'}</p><p>Bark 提醒：${delivery[m?.alert_notification_state]||'未知'} · 企业微信详情：${delivery[m?.notification_state]||'未知'}</p></div>`:'<p class="subtle" role="status">正在读取存储状态…</p>'}
      <p class="subtle">每 5 分钟巡检；使用率 80% / 90%，剩余 5 / 2 GiB，inode 80% / 90% 分级提醒。同级最多每日一次，升级与恢复另报。后台暂停车辆采集不暂停磁盘巡检。</p>
      <hr><h3>历史完整快照</h3><p class="subtle">范围：全部车辆的完整快照归档。当前月份、凭据、最新车况、轨迹、事件和部署备份不可删除。按北京时间分年保留，无自动清理。</p>
      ${inventory?list(inventory.archives,false):'<p class="subtle">正在读取归档列表…</p>'}
      <h3 class="storage-subhead">回收区</h3>${inventory?list(inventory.trash,true):''}
      ${plan?`<section class="storage-confirm" aria-label="操作预览"><h3>${{trash:'移入回收区',restore:'恢复归档',purge:'永久删除归档'}[plan.action]} · ${escape(plan.partition)}</h3><p>全部车辆 · ${Number.isFinite(plan.reads)?plan.reads+' 次读取':'记录数未知'} · ${bytes(plan.bytes)}</p><p>${plan.action==='purge'?'不可恢复。只删除该回收文件，不删除其他备份；预计释放 '+bytes(plan.released_bytes)+'，实际以文件系统为准。':plan.action==='trash'?'可从回收区恢复；不会释放磁盘空间。':'恢复到原月份；不会覆盖已存在的数据。'}</p><p class="subtle">预览有效 5 分钟；文件变化后须重新预览。</p><label>输入「${escape(plan.confirmation)}」确认<input id="storage-confirm-input" autocomplete="off" value="${escape(draft)}" ${busy?'disabled':''}></label><div class="storage-actions">${button('取消','cancel','',busy)}${button(plan.action==='purge'?'确认永久删除':'确认执行','execute','',busy||draft!==plan.confirmation,plan.action==='purge')}</div></section>`:''}
      </div>`;
  }
  async function reload(){
    const version=++sequence;busy=true;error='';draw();
    try{
      const result=await Promise.all([request('/api/storage'),request('/api/storage/archives')]);
      if(version!==sequence)return;
      [status,inventory]=result;loadedAt=Date.now();
    }catch(e){if(version===sequence)error=e.message;}
    finally{if(version===sequence){busy=false;draw();}}
  }
  async function click(event){
    const target=event.target.closest('[data-storage-action]');if(!target)return;
    event.stopPropagation();if(busy)return;
    const action=target.dataset.storageAction;
    if(action==='reload'){plan=null;draft='';return reload();}
    if(action==='cancel'){sequence++;plan=null;draft='';error='';draw();return;}
    busy=true;error='';message='';const version=++sequence;draw();
    try{
      if(action==='execute'){
        if(!plan||draft!==plan.confirmation)throw Error('请按预览输入完整确认文字。');
        const result=await request('/api/storage/execute',{token:plan.token,confirmation:draft});
        if(version!==sequence)return;
        plan=null;draft='';message=result.audit_warning||`${result.partition} 操作完成。${result.action==='purge'?'永久删除不可恢复；独立备份不受影响。':result.action==='trash'?'可在回收区恢复，尚未释放空间。':'已恢复。'}`;
        busy=false;await reload();
      }else if(['trash','restore','purge'].includes(action)){
        plan=null;draft='';
        const result=await request('/api/storage/preview',{action,target:target.dataset.target});
        if(version!==sequence)return;
        plan=result;
      }
    }catch(e){if(version===sequence){error=e.message;if(action==='execute'){plan=null;draft='';}}}
    finally{if(version===sequence){busy=false;draw();if(plan)panel.querySelector('.storage-confirm')?.scrollIntoView({block:'nearest',behavior:'auto'});}}
  }
  return {mount(root,api){
    request=api;
    if(!panel){panel=document.createElement('section');panel.id='storage-management';panel.className='card section-gap';panel.addEventListener('click',click);panel.addEventListener('input',event=>{if(event.target.id==='storage-confirm-input'){draft=event.target.value;const b=panel.querySelector('[data-storage-action="execute"]');if(b)b.disabled=busy||draft!==plan?.confirmation;}});draw();}
    root.querySelector('section')?.after(panel);
    if(!busy&&!plan&&Date.now()-loadedAt>60000)reload();
  }};
})();
