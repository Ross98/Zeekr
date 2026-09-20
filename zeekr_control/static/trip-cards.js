(function(root){
  'use strict';
  const dateAt=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const number=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value):'未知';
  const blank=()=>({title:'一段用车记录',note:'',location:'',showDistance:true,showTime:true,showSoc:true,showCharge:false,showLocation:false,showPhoto:true,theme:'auto'});
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',month=dateAt(Date.now()).slice(0,7),data=null,selected='',chargeId='',settings=blank(),photo=null;
    let attempted=false,loading=false,photoLoading=false,exporting=false,error='',status='',serial=0,photoSerial=0,cardSerial=0;
    const context=()=>getState()?.insights_context||'';
    const valid=(token,current,identity)=>token===current&&owner===identity&&context()===identity;
    const trip=()=>data?.trips.find(r=>r.id===selected);
    const charge=()=>data?.charges.find(r=>r.id===chargeId);
    const button=(label,action,disabled=false)=>`<button class="button secondary" data-trip-card="${action}" ${disabled||exporting?'disabled':''}>${label}</button>`;
    function clearDraft(){settings=blank();photo=null;photoSerial++;cardSerial++;photoLoading=false;status='';}
    function paint(){
      if(!node?.isConnected||!active())return;
      const current=trip();
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">行程卡片</span><h2>把一趟路，留成一张图</h2><p>选择要留下的数字，配上自己的照片和文字。</p></div><span class="insight-source">浏览器本地导出 · PNG</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>卡片记录月份<input id="trip-card-month" type="month" value="${esc(month)}" ${exporting?'disabled':''}></label>${button('读取卡片素材','load',!owner||!month||loading)}</div>${loading?'<p role="status">正在读取安全摘要…</p>':''}${photoLoading?'<p role="status">正在处理本机照片…</p>':''}${status?`<p role="status" class="insight-note">${esc(status)}</p>`:''}${error?`<p role="alert" class="notice error">${esc(error)}</p>`:''}${!owner?'<p>等待当前账号的车辆缓存后，可选择已结束行程。</p>':''}${data?`<p class="insight-note">素材月份 ${data.window.start_date.slice(0,7)}，按事件结束日期归期。${data.trips.length} 条行程，${data.charges.length} 条充电记录。</p>`:''}<p class="insight-note">照片、备注和手填地点只留在当前浏览器，导出时不上传。地点默认隐藏；切换行程会清空照片和文字。图片不包含车辆身份、原始位置或账号凭据。</p>
        ${data?`<label>卡片行程<select id="trip-card-selection" aria-label="卡片行程" ${exporting?'disabled':''}><option value="">选择一趟已结束行程</option>${data.trips.map(r=>`<option value="${esc(r.id)}" ${r.id===selected?'selected':''}>${esc(time(r.end_time))} · ${number(r.distance_km)} km${r.partial?' · 片段':''}</option>`).join('')}</select></label>${!data.trips.length?'<p class="insight-empty">本月没有可选的已结束行程。</p>':''}`:''}</section>
        ${current?`<div class="trip-card-layout"><section class="card insight-panel"><h3>卡片内容</h3><div class="trip-card-fields"><label>卡片标题<input id="trip-card-title" data-card-text="title" maxlength="60" value="${esc(settings.title)}" ${exporting?'disabled':''}></label><div class="trip-card-checks">${[['showDistance','显示行程里程'],['showTime','显示时间与时长'],['showSoc','显示起止 SOC'],['showCharge','附带一条充电记录'],['showLocation','显示手填地点'],['showPhoto','显示所选照片']].map(([key,label])=>`<label><input type="checkbox" data-card-toggle="${key}" ${settings[key]?'checked':''} ${exporting?'disabled':''}>${label}</label>`).join('')}</div><label>附带的充电记录<select id="trip-card-charge" aria-label="附带的充电记录" ${!settings.showCharge||exporting?'disabled':''}><option value="">请选择一条本月充电记录</option>${data.charges.map(r=>`<option value="${esc(r.id)}" ${chargeId===r.id?'selected':''}>${esc(time(r.end_time))} · ${number(r.start_soc)}% → ${number(r.end_soc)}%</option>`).join('')}</select></label><p class="insight-note">附带充电由你选择，是独立记录；不解释为这趟行程的用电或费用。</p><label>手填地点<input id="trip-card-location" data-card-text="location" maxlength="80" value="${esc(settings.location)}" ${!settings.showLocation||exporting?'disabled':''}></label><label>卡片备注<textarea id="trip-card-note" aria-label="卡片备注" data-card-text="note" maxlength="400" rows="5" ${exporting?'disabled':''}>${esc(settings.note)}</textarea></label><label>选择本机照片<input id="trip-card-photo" aria-label="选择本机照片" type="file" accept="image/png,image/jpeg,image/webp" ${exporting||photoLoading?'disabled':''}></label><p class="insight-note">PNG / JPEG / WebP，最多 8 MiB、2400 万像素；照片完整适配画框，不裁掉边缘。导出重绘像素，不带原照片文件名或元数据。</p>${button('移除照片','remove-photo',!photo&&!photoLoading)}<label>卡片外观<select id="trip-card-theme" aria-label="卡片外观" ${exporting?'disabled':''}>${[['auto','跟随页面'],['light','日间'],['dark','夜间']].map(([key,label])=>`<option value="${key}" ${settings.theme===key?'selected':''}>${label}</option>`).join('')}</select></label><div class="insight-actions">${button('查看卡片预览','preview')}${button('导出 PNG 图片','export',photoLoading||settings.showCharge&&!charge())}</div></div></section><section class="card insight-panel" id="trip-card-preview"><div class="insight-heading"><h3>导出预览</h3><span class="insight-badge">1440 像素宽</span></div><canvas id="trip-card-canvas" role="img" aria-label="行程卡片预览；下方提供图片内文字"></canvas><div id="trip-card-description" class="trip-card-description"></div></section></div>`:''}`;
      paintPreview();
    }
    function paintPreview(){
      const canvas=node?.querySelector('#trip-card-canvas'),current=trip();if(!canvas||!current||!active())return;
      const model=root.TripCardRenderer.describe(current,charge(),settings);
      const theme=settings.theme==='auto'?(document.documentElement.dataset.theme==='dark'?'dark':'light'):settings.theme;
      root.TripCardRenderer.draw(canvas,model,{theme,photo:settings.showPhoto?photo:null});
      const text=[model.title,model.quality,model.period,...model.metrics.map(m=>m.label+' '+m.value+' '+m.unit),
        ...(model.charge?[model.charge.title,...model.charge.lines]:[]),model.note,...(model.location?['地点 · 手动填写',model.location]:[]),model.footnote].filter(Boolean);
      node.querySelector('#trip-card-description').innerHTML='<h4>图片包含的文字</h4>'+text.map(line=>`<p>${esc(line)}</p>`).join('');
      node.querySelector('[data-trip-card="export"]').disabled=exporting||photoLoading||settings.showCharge&&!charge();
    }
    async function load(){
      if(!owner||!month)return;const identity=owner,token=++serial;loading=attempted=true;error='';paint();
      try{const result=await request('/api/insights/cards?date='+encodeURIComponent(month+'-01'));
        if(!valid(token,serial,identity))return;if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=result;if(!data.trips.some(r=>r.id===selected)){selected=data.trips[0]?.id||'';chargeId='';clearDraft();}
        if(!data.charges.some(r=>r.id===chargeId))chargeId='';
      }catch(failure){if(valid(token,serial,identity))error=failure.message+' 原预览保留，请核对素材月份。';}
      finally{if(valid(token,serial,identity)){loading=false;paint();}}
    }
    async function loadPhoto(file){
      if(!file)return;const identity=owner,token=++photoSerial;photoLoading=true;error=status='';paint();
      let bitmap;
      try{
        if(file.size>8*1024*1024)throw Error('照片不得超过 8 MiB。');
        const bytes=await file.arrayBuffer();if(!valid(token,photoSerial,identity))return;
        const dimensions=root.TripCardRenderer.imageSize(bytes);
        bitmap=await createImageBitmap(new Blob([bytes],{type:dimensions.type}));
        if(!valid(token,photoSerial,identity))return;
        if(bitmap.width*bitmap.height>24000000||Math.max(bitmap.width,bitmap.height)>12000)throw Error('照片尺寸超过限制。');
        const scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height));
        const thumb=document.createElement('canvas');thumb.width=Math.max(1,Math.round(bitmap.width*scale));thumb.height=Math.max(1,Math.round(bitmap.height*scale));
        thumb.getContext('2d').drawImage(bitmap,0,0,thumb.width,thumb.height);photo=thumb;cardSerial++;status='照片已在浏览器内载入。';
      }catch(failure){if(valid(token,photoSerial,identity))error=failure.message+(photo?' 原照片保留。':'');}
      finally{bitmap?.close();if(valid(token,photoSerial,identity)){photoLoading=false;paint();}}
    }
    async function exportImage(){
      const canvas=node?.querySelector('#trip-card-canvas');if(!canvas||exporting||photoLoading||settings.showCharge&&!charge())return;
      const identity=owner,token=cardSerial;exporting=true;error=status='';paint();
      try{
        const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
        if(!valid(token,cardSerial,identity))return;if(!blob)throw Error('图片导出失败，请重试。');
        const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='trip-card.png';link.click();setTimeout(()=>URL.revokeObjectURL(url),15000);
        status='PNG 已交给浏览器下载。';
      }catch(failure){if(valid(token,cardSerial,identity))error=failure.message;}
      finally{if(owner===identity&&context()===identity){exporting=false;paint();}}
    }
    let tripRevision;
    function mount(container){
      const changed=owner!==context()||tripRevision!==getState()?.trip_records_revision,remount=node!==container;node=container;
      tripRevision=getState()?.trip_records_revision;
      if(changed){owner=context();data=null;selected=chargeId='';attempted=loading=exporting=false;error='';serial++;clearDraft();}
      if(changed||remount)paint();if(owner&&!attempted&&!loading)load();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;const el=event.target;
      if(event.type==='input'){
        if(el.id==='trip-card-month'){month=el.value;return true;}
        if(el.dataset.cardText){settings[el.dataset.cardText]=el.value;cardSerial++;paintPreview();return true;}
      }
      if(event.type==='change'){
        if(el.id==='trip-card-selection'){selected=el.value;chargeId='';clearDraft();error='';paint();return true;}
        if(el.id==='trip-card-charge'){chargeId=el.value;cardSerial++;paintPreview();return true;}
        if(el.id==='trip-card-theme'){settings.theme=el.value;cardSerial++;paintPreview();return true;}
        if(el.id==='trip-card-photo'){loadPhoto(el.files?.[0]);return true;}
        if(el.dataset.cardToggle){settings[el.dataset.cardToggle]=el.checked;cardSerial++;
          node.querySelector('#trip-card-location').disabled=!settings.showLocation||exporting;
          node.querySelector('#trip-card-charge').disabled=!settings.showCharge||exporting;paintPreview();return true;}
      }
      if(event.type!=='click')return false;const target=el.closest('[data-trip-card]');if(!target||target.disabled)return false;
      const action=target.dataset.tripCard;
      if(action==='load')load();else if(action==='export')exportImage();else if(action==='preview')node.querySelector('#trip-card-preview').scrollIntoView({block:'start'});
      else if(action==='remove-photo'){photo=null;photoSerial++;photoLoading=false;cardSerial++;error=status='';paint();}
      return true;
    }
    new MutationObserver(()=>{if(active()&&settings.theme==='auto')paintPreview();}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
    return {mount,handle};
  }
  root.TripCardsPage={create};
})(window);
