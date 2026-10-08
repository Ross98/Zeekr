(function(root){
  'use strict';
  const number=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value):'—';
  const monthNow=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit'}).format(new Date());
  function freehandVertices(samples){
    if(samples.length<3)return [];
    const first=samples[0],points=[...samples];
    if(Math.hypot(points.at(-1).x-first.x,points.at(-1).y-first.y)<=2)points.pop();
    points.push(first);
    function simplify(tolerance){
      const keep=new Set([0,points.length-1]),stack=[[0,points.length-1]];
      while(stack.length){
        const [start,end]=stack.pop(),a=points[start],b=points[end],dx=b.x-a.x,dy=b.y-a.y,length=dx*dx+dy*dy;
        let farthest=-1,distance=tolerance*tolerance;
        for(let i=start+1;i<end;i++){
          const p=points[i],fraction=length?Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/length)):0;
          const squared=(p.x-a.x-fraction*dx)**2+(p.y-a.y-fraction*dy)**2;
          if(squared>distance){distance=squared;farthest=i;}
        }
        if(farthest!==-1){keep.add(farthest);stack.push([start,farthest],[farthest,end]);}
      }
      return [...keep].sort((a,b)=>a-b).slice(0,-1).map(index=>points[index]);
    }
    let tolerance=2,ring=simplify(tolerance);
    while(ring.length>100){tolerance*=1.5;ring=simplify(tolerance);}
    const area=Math.abs(ring.reduce((sum,a,i)=>{const b=ring[(i+1)%ring.length];return sum+a.x*b.y-b.x*a.y;},0))/2;
    return ring.length>=3&&area>=20?ring.map(p=>[p.lat,p.lng]):[];
  }
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',month=monthNow(),data=null,selected=null,tags='',note='',attempted=false,loading=false,busy=false;
    let serial=0,writeSerial=0,error='',status='',filter='',completeness='all',groupA='',groupB='',page=0,trashPage=0;
    let routeShown=false,routeBusy=false,routeData=null,routeError='',routeSerial=0,routeMap=null;
    let namePlace=null,nameDraft='',nameRadius=150,namePreview=null;
    let nameShape='circle',nameVertices=[],nameDrawing=false,nameMap=null,nameViewport=null,nameVertex=null,nameFreehand=true;
    let placesShown=false,placesMap=null,placePage=0,focusedPlace=null,focusedRegion=null,placesViewport=null;
    let commuteDraft={home:null,work:null,homeRadius:300,workRadius:300},commuteDirty=false;
    let commuteMap=null,commuteShown=false,placeMode=null,commuteBusy=false;
    const context=()=>getState()?.insights_context||'';
    const valid=(token,current,identity)=>token===current&&owner===identity&&context()===identity;
    const button=(label,action,disabled=false,extra='')=>`<button class="button secondary" data-tag="${action}" ${disabled||busy?'disabled':''} ${extra}>${label}</button>`;
    const options=value=>(data?.groups||[]).map(g=>`<option value="${esc(g.tag)}" ${g.tag===value?'selected':''}>${esc(g.tag)}</option>`).join('');
    const filterOptions=()=>(data?.groups||[]).map(g=>`<option value="${esc('tag:'+g.tag)}" ${filter==='tag:'+g.tag?'selected':''}>${g.tag==='未标注'?'标签：':''}${esc(g.tag)}</option>`).join('');
    const labelList=()=>[...new Set(tags.split(/[,，\n]/).map(s=>s.trim()).filter(Boolean))];
    function syncQuickLabels(){
      const selected=new Set(labelList());
      node?.querySelectorAll('[data-tag="toggle-label"]').forEach(button=>{
        const used=selected.has(button.dataset.label);
        button.setAttribute('aria-pressed',String(used));
        button.setAttribute('aria-label',`${used?'取消':'选择'}标签 ${button.dataset.label}`);
      });
    }
    const tripDate=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
    function closeRoute(){routeSerial++;routeShown=routeBusy=false;routeData=null;routeError='';routeMap?.remove();routeMap=null;}
    function closeCommuteMap(){commuteMap?.remove();commuteMap=null;commuteShown=false;placeMode=null;}
    function syncCommuteRule(){
      if(commuteDirty)return;
      const rule=data?.commute_rule;
      commuteDraft={home:rule?.home?{latitude:rule.home.latitude,longitude:rule.home.longitude}:null,
        work:rule?.work?{latitude:rule.work.latitude,longitude:rule.work.longitude}:null,
        homeRadius:rule?.home?.radius_m||300,workRadius:rule?.work?.radius_m||300};
    }
    const placeLabel=id=>data?.place_statistics?.places.find(p=>p.id===id)?.label||'未知';
    const placeLink=id=>data?.place_statistics?.places.some(p=>p.id===id)?`<button type="button" class="tag-place-link" data-tag="place-focus" data-id="${esc(id)}" aria-label="在地图定位 ${esc(placeLabel(id))}" ${busy?'disabled':''}>${esc(placeLabel(id))}</button>`:esc(placeLabel(id));
    function closeNameEditor(){nameMap?.remove();nameMap=null;namePlace=null;nameDraft='';namePreview=null;nameVertices=[];nameDrawing=false;nameVertex=null;nameViewport=null;}
    function closePlacesMap(){closeNameEditor();placesMap?.remove();placesMap=null;placesShown=false;placePage=0;focusedPlace=focusedRegion=placesViewport=null;namePlace=null;nameDraft='';namePreview=null;}
    function selectMapPlace(id,region=false){
      focusedPlace=region?null:id;focusedRegion=region?id:null;placesViewport=null;
      placesShown=true;placesMap?.remove();placesMap=null;
    }
    function focusPlace(id,region=false){
      const items=region?data?.place_statistics?.name_regions:data?.place_statistics?.places;
      if(!items?.some(p=>p.id===id))return;
      if(namePlace&&(region?(namePlace.region_id||namePlace.manual_name_id)!==id:namePlace.id!==id))closeNameEditor();
      selectMapPlace(id,region);paint();
      const map=node.querySelector('#tag-places-map');map?.focus({preventScroll:true});map?.scrollIntoView({block:'center'});
    }
    function regionLayer(map,region,color='#20776e'){
      return region.shape==='polygon'?L.polygon(region.vertices,{color,fillOpacity:.12}).addTo(map):
        L.circle([region.latitude,region.longitude],{radius:region.radius_m||150,color,fillOpacity:.12}).addTo(map);
    }
    function invalidateName(){namePreview=null;}
    function openNameEditor(place){
      closeNameEditor();namePlace=place;nameDraft=place.name_source==='manual'?place.label:'';
      nameRadius=place.name_radius_m||150;nameShape=place.name_shape||'circle';
      nameVertices=(place.name_vertices||[]).map(p=>[...p]);nameDrawing=false;
      selectMapPlace(place.region_id||place.id,Boolean(place.region_id));paint();
      node.querySelector('#tag-place-name')?.focus({preventScroll:true});
      node.querySelector('#tag-place-name-editor')?.scrollIntoView({block:'nearest'});
    }
    function placesView(){
      const stats=data?.place_statistics;if(!stats)return '';
      const places=[...stats.places].sort((a,b)=>(b.departures+b.arrivals)-(a.departures+a.arrivals)||a.id.localeCompare(b.id));
      const regions=stats.name_regions||[],pages=Math.max(1,Math.ceil(places.length/20));placePage=Math.min(placePage,pages-1);
      return `<section class="card insight-panel" id="tag-place-statistics"><div class="insight-heading"><h3>本月出发与到达地点</h3><span class="insight-note">${places.length} 个参考地点</span></div>
        <p class="insight-note">已命名区域内的起止点共用地点标签，历史与后续月份自动匹配；按点位圆心判断区域归属，圆心在多边形边界上也算范围内；圆心在外仅圆边重叠不归入。未命名点仍按固定中心 ${stats.radius_m} 米分组，不沿相邻点串联合并。使用起止三分钟内的可信采样，原始坐标保留。</p>
        <p class="insight-note">名称优先使用手动命名，其次按当前设置匹配家／公司，再采用已有可信地址。地址带“附近”，无法确认时保留编号；读取统计不会额外查询地址。</p>
        <p class="insight-note">出发地点未知 ${stats.unknown_departures} 次 · 到达地点未知 ${stats.unknown_arrivals} 次。完整与片段均按有效端点计入；次数表示行程端点，不表示停车时长。</p>
        ${places.length?`<table class="tag-place-table"><thead><tr><th scope="col">地点</th><th scope="col">出发</th><th scope="col">到达</th><th scope="col">名称</th></tr></thead><tbody>${places.slice(placePage*20,placePage*20+20).map(p=>`<tr><th scope="row">${placeLink(p.id)}<small class="tag-place-source">${({manual:'手动名称',commute:'按当前设置',address:'已有地址',reference:'参考编号'})[p.name_source]||'参考编号'}</small></th><td>${p.departures}</td><td>${p.arrivals}</td><td>${button('改名','place-name-edit',!p.name_key,`data-id="${esc(p.id)}" aria-label="修改地点名称 ${esc(p.label)}"`)}</td></tr>`).join('')}</tbody></table>${pages>1?`<div class="insight-pagination">${button('上一页地点','places-previous',placePage===0)}<span>${placePage+1} / ${pages}</span>${button('下一页地点','places-next',placePage+1===pages)}</div>`:''}`:'<p>本月暂无可信起止定位，仍可创建或管理地点区域。</p>'}
        <h4>已保存地点区域</h4><p class="insight-note">区域跨月保留，本月没有行程也可修改。不同区域即使同名也分别保存。</p>
        <div class="tag-region-list">${regions.map(r=>`<div><button type="button" class="tag-place-link" data-tag="region-focus" data-id="${esc(r.id)}" aria-label="在地图定位 ${esc(r.name)}">${esc(r.name)}</button><span>${r.shape==='polygon'?`多边形 · ${r.vertices.length} 个顶点`:`圆形 · ${r.radius_m||150} 米`}</span>${button('编辑区域','region-edit',false,`data-id="${esc(r.id)}" aria-label="编辑区域 ${esc(r.name)}"`)}</div>`).join('')||'<p class="insight-note">暂无已保存区域。</p>'}</div>
        <div class="insight-actions">${button('新建多边形地点','region-new')}${button('撤销地点操作','place-name-undo',!stats.name_can_undo)}</div>
        ${namePlace?nameEditor():''}
        <div class="insight-actions">${button(placesShown?'隐藏地点地图':'查看地点地图','places-map',!places.length&&!regions.length)}${placesShown?button('查看全部地点','places-all'):''}</div>${placesShown?'<p class="insight-note">点地点名称可放大定位；点编号查看详情和地图网站跳转。小点为本月实际起止观测。</p><div id="tag-places-map" role="region" tabindex="0" aria-label="本月地点地图"></div>':''}
        <h4>常见方向</h4>${stats.routes.length?`<div class="tag-place-routes">${stats.routes.slice(0,10).map(r=>`<p><span>${placeLink(r.start_place)} → ${placeLink(r.end_place)}</span><strong>${r.count} 趟</strong></p>`).join('')}</div><p class="insight-note">按方向分别统计，仅列次数最多的前 10 组；缺少任一端点不计入方向。同地点往返也保留。</p>`:'<p class="insight-note">尚无两端都能归类的行程。</p>'}</section>`;
    }
    function nameEditor(){
      const polygon=nameShape==='polygon',ready=!polygon||nameVertices.length>=3&&!nameDrawing;
      const conflicts=namePreview?.conflicts||[],blocking=polygon&&conflicts.some(c=>c.shape==='polygon');
      return `<div id="tag-place-name-editor" role="group" aria-labelledby="tag-place-name-heading"><h4 id="tag-place-name-heading">修改地点名称 · ${esc(namePlace.label)}</h4><label>地点名称<input id="tag-place-name" aria-label="地点名称" maxlength="40" value="${esc(nameDraft)}" ${busy?'disabled':''}></label>
        <label>区域形状<select id="tag-name-shape" aria-label="区域形状" ${busy?'disabled':''}>${[['circle','圆形范围'],['polygon','自定义多边形']].map(([value,label])=>`<option value="${value}" ${nameShape===value?'selected':''} ${value==='circle'&&namePlace.isNew?'disabled':''}>${label}</option>`).join('')}</select></label>
        ${polygon?`<p class="insight-note">${nameDrawing?(nameFreehand?'按住鼠标左键沿边界连续圈画，松开后自动闭合。圈画时地图不随鼠标平移。':'点击地图添加顶点，按顺序沿边界绘制，再按“闭合区域”。'):'可拖动顶点调整边界，点顶点选中后可删除。要重新圈画，请按“重新圈画”；浏览地图时可拖动地图平移。'}按点位圆心判断归属，圆心在边界上也归入；圆边重叠但圆心在外不归入。</p>
        <label>绘制方式<select id="tag-region-method" aria-label="绘制方式" ${busy?'disabled':''}><option value="freehand" ${nameFreehand?'selected':''}>鼠标连续圈画</option><option value="points" ${!nameFreehand?'selected':''}>逐点绘制</option></select></label>
        <div class="insight-actions">${nameFreehand?button('重新圈画','region-freehand'):button(nameDrawing?'闭合区域':'继续添加顶点',nameDrawing?'region-finish':'region-draw',nameDrawing&&nameVertices.length<3)}${button('浏览地图','region-browse')}${button('撤回最后一个点','region-pop',!nameVertices.length)}${button('重新绘制','region-reset')}</div>
        <div id="tag-name-map" class="${nameDrawing&&nameFreehand?'region-freehand':''}" role="region" tabindex="0" aria-label="地点区域绘制地图"></div>
        <div class="tag-vertex-controls"><label>选择顶点<select id="tag-region-vertex" aria-label="选择顶点" ${busy?'disabled':''}><option value="">未选择</option>${nameVertices.map((_,i)=>`<option value="${i}" ${nameVertex===i?'selected':''}>顶点 ${i+1}</option>`).join('')}</select></label>${button('删除选中顶点','region-delete-vertex',nameVertex===null)}${button('将地图中心加入边界','region-add-center',nameFreehand||!nameDrawing||nameVertices.length>=100)}</div><p class="insight-note">${nameVertices.length} 个顶点。圈画松开后自动闭合，细小抖动会整理为可调整的顶点。小点为本月实际起止观测；其他已保存区域作为边界参考。</p>`:
        `<label>命名匹配范围<select id="tag-name-radius" aria-label="命名匹配范围" ${busy?'disabled':''}>${[25,50,100,150].map(r=>`<option value="${r}" ${nameRadius===r?'selected':''}>${r} 米</option>`).join('')}</select></label>`}
        <p class="insight-note">先预览本月受影响行程，保存后历史与新行程按区域自动命名。预览不改记录，恢复自动名称只清除这个区域的手动标签。</p>
        ${namePreview?`<div id="tag-name-preview"><p>本月可能影响 ${namePreview.affected_count} 趟行程 · ${polygon?`多边形 ${namePreview.vertex_count} 个顶点`:`命名范围 ${namePreview.radius_m} 米`}</p>${conflicts.length?`<p class="notice ${blocking?'error':''}">与 ${conflicts.map(c=>esc(c.name)).join('、')} 的命名范围重叠；${blocking?'多边形之间不能重叠，请调整边界后重新预览。':polygon||conflicts.some(c=>c.shape==='polygon')?'可以保存，圆心落入多边形的点位采用多边形名称，圆心在外保留圆形名称。':'可以保存，重叠的圆形范围按最近中心归属。'}</p>`:''}<div class="report-event-list">${namePreview.affected.slice(0,20).map(r=>`<article><span>${esc(time(data.events.find(e=>e.id===r.id)?.end_time))}</span><span>${r.sides.map(side=>side==='start'?'出发':'到达').join('、')} · ${r.within_range?'范围内':'调整后在范围外'}</span></article>`).join('')}</div>${namePreview.affected_count>20?'<p>仅展示前 20 趟；数量为本月全部可能受影响行程。</p>':''}</div>`:''}
        <div class="insight-actions">${button('预览影响行程','place-name-preview',loading||!ready)}${button('保存地点名称','place-name-save',loading||!ready||!namePreview||blocking)}${namePlace.manual_name_id?button('恢复自动名称','place-name-clear',loading):''}${button('取消地点命名','place-name-cancel')}</div></div>`;
    }
    function paintNameMap(){
      const el=node?.querySelector('#tag-name-map');if(!el||nameMap)return;
      nameMap=AmapMaps.createMap(el,{scrollWheelZoom:false,doubleClickZoom:false});AmapMaps.addTiles(nameMap);
      const regions=data.place_statistics.name_regions||[],points=data.place_statistics.observed_points||[];
      for(const region of regions){
        if(region.id===namePlace.region_id||region.id===namePlace.manual_name_id)continue;
        regionLayer(nameMap,region,'#66746e').bindTooltip(esc(region.name));
      }
      for(const p of points)L.circleMarker([p.latitude,p.longitude],{radius:3,color:'#16594f',fillOpacity:.6}).addTo(nameMap);
      if(nameVertices.length>=3)L.polygon(nameVertices,{color:'#20776e',fillOpacity:.16,interactive:false}).addTo(nameMap);
      else if(nameVertices.length)L.polyline(nameVertices,{color:'#20776e',interactive:false}).addTo(nameMap);
      nameVertices.forEach((point,index)=>{
        const icon=L.divIcon({className:'tag-place-marker',html:`<span>${index+1}</span>`,iconSize:[32,32],iconAnchor:[16,16]});
        L.marker(point,{draggable:!busy,icon,title:`区域顶点 ${index+1}`}).addTo(nameMap).on('dragend',event=>{
          if(busy)return;const p=event.target.getLatLng();nameVertices[index]=[p.lat,p.lng];nameVertex=index;invalidateName();paint();
        }).on('click',()=>{if(busy)return;nameVertex=index;paint();});
      });
      if(nameViewport)nameMap.setView(nameViewport.center,nameViewport.zoom,{animate:false});
      else if(nameVertices.length>=3)nameMap.fitBounds(nameVertices,{padding:[40,40],maxZoom:18});
      else if(namePlace.latitude!==undefined)nameMap.setView([namePlace.latitude,namePlace.longitude],17);
      else if(points.length)nameMap.fitBounds(points.map(p=>[p.latitude,p.longitude]),{padding:[40,40],maxZoom:17});
      else if(regions.length)nameMap.setView([regions[0].latitude,regions[0].longitude],16);
      else nameMap.setView([35,105],4);
      if(nameFreehand&&nameDrawing&&!busy){nameMap.dragging.disable();bindFreehand(el,nameMap);}
      nameMap.on('click',event=>{if(!nameDrawing||nameFreehand||busy||nameVertices.length>=100)return;nameVertices.push([event.latlng.lat,event.latlng.lng]);nameVertex=nameVertices.length-1;invalidateName();paint();});
    }
    function bindFreehand(el,map){
      let pointer=null,stroke=[],line=null;
      function add(event){
        const pixel=map.mouseEventToContainerPoint(event),point=map.containerPointToLatLng(pixel),previous=stroke.at(-1);
        if(previous&&Math.hypot(previous.x-pixel.x,previous.y-pixel.y)<2)return;
        const sample={x:pixel.x,y:pixel.y,lat:point.lat,lng:point.lng};
        if(stroke.length<8192)stroke.push(sample);else stroke[stroke.length-1]=sample;
        line.setLatLngs(stroke.map(p=>[p.lat,p.lng]));
      }
      function cancel(){pointer=null;line?.remove();line=null;stroke=[];}
      el.addEventListener('pointerdown',event=>{
        if(event.button!==0||event.pointerType!=='mouse'||pointer!==null||event.target.closest('.leaflet-control,.leaflet-marker-icon'))return;
        event.preventDefault();event.stopPropagation();pointer=event.pointerId;stroke=[];
        el.setPointerCapture(pointer);line=L.polyline([],{color:'#20776e',weight:3,interactive:false}).addTo(map);add(event);
      },true);
      el.addEventListener('pointermove',event=>{if(event.pointerId!==pointer)return;event.preventDefault();event.stopPropagation();add(event);},true);
      el.addEventListener('pointerup',event=>{
        if(event.pointerId!==pointer)return;event.preventDefault();event.stopPropagation();add(event);
        const vertices=freehandVertices(stroke),capture=pointer;cancel();el.releasePointerCapture(capture);
        if(vertices.length){nameVertices=vertices;nameDrawing=false;nameVertex=null;invalidateName();error='';}
        else error='圈画太小或没有围成区域，请按住鼠标重新圈画。';
        paint();
      },true);
      el.addEventListener('pointercancel',cancel);
      el.addEventListener('lostpointercapture',cancel);
      el.addEventListener('keydown',event=>{if(event.key==='Escape'&&pointer!==null){const capture=pointer;cancel();el.releasePointerCapture(capture);event.preventDefault();}},true);
    }
    function paintPlacesMap(){
      const el=node?.querySelector('#tag-places-map'),places=data?.place_statistics?.places||[],regions=data?.place_statistics?.name_regions||[];if(!el||(!places.length&&!regions.length)||placesMap)return;
      placesMap=AmapMaps.createMap(el,{scrollWheelZoom:false});
      AmapMaps.addTiles(placesMap);
      const bounds=[],markers=new Map(),regionLayers=new Map();
      for(const region of regions){
        const layer=regionLayer(placesMap,region).bindTooltip(esc(region.name))
          .bindPopup(`<strong>${esc(region.name)}</strong><p>已保存地点区域 · ${region.shape==='polygon'?'自定义多边形':(region.radius_m||150)+' 米圆形范围'}</p>`);
        layer.on('click',()=>focusPlace(region.id,true));regionLayers.set(region.id,layer);
        bounds.push(...(region.shape==='polygon'?region.vertices:[[region.latitude,region.longitude]]));
      }
      for(const p of data.place_statistics.observed_points||[])L.circleMarker([p.latitude,p.longitude],{radius:3,color:'#16594f',fillOpacity:.6}).addTo(placesMap);
      for(const [index,p] of places.entries()){
        const center=[p.latitude,p.longitude];bounds.push(center);
        if(p.name_shape==='polygon')L.polygon(p.name_vertices,{color:'#20776e',fillOpacity:.12}).addTo(placesMap);else L.circle(center,{radius:p.name_radius_m||data.place_statistics.radius_m,color:'#20776e',fillOpacity:.12}).addTo(placesMap);
        const icon=L.divIcon({className:'tag-place-marker',html:`<span>${index+1}</span>`,iconSize:[32,32],iconAnchor:[16,16]});
        const href=`https://uri.amap.com/marker?position=${p.longitude},${p.latitude}&coordinate=wgs84&name=${encodeURIComponent(p.display_name||p.name||"地点")}`;
        const marker=L.marker(center,{icon,title:p.label}).addTo(placesMap)
          .bindTooltip(esc(p.label))
          .bindPopup(`<strong>${esc(p.label)}</strong><p>出发 ${p.departures} 次 · 到达 ${p.arrivals} 次<br>归并范围 ${p.name_shape==='polygon'?'自定义多边形':(p.name_radius_m||data.place_statistics.radius_m)+' 米'}</p><a href="${esc(href)}" target="_blank" rel="noopener noreferrer">打开地图网站</a>`);
        marker.on('click',()=>focusPlace(p.id));markers.set(p.id,marker);
      }
      const selectedPlace=places.find(p=>p.id===focusedPlace),selectedRegion=regions.find(r=>r.id===focusedRegion);
      if(placesViewport)placesMap.setView(placesViewport.center,placesViewport.zoom,{animate:false});
      else if(selectedRegion?.shape==='polygon')placesMap.fitBounds(selectedRegion.vertices,{padding:[35,35],maxZoom:18,animate:false});
      else if(selectedRegion)placesMap.setView([selectedRegion.latitude,selectedRegion.longitude],17,{animate:false});
      else if(selectedPlace)placesMap.setView([selectedPlace.latitude,selectedPlace.longitude],17,{animate:false});
      else if(bounds.length===1)placesMap.setView(bounds[0],16);else placesMap.fitBounds(bounds,{padding:[35,35],maxZoom:16});
      if(selectedPlace)markers.get(selectedPlace.id)?.openPopup();
      if(selectedRegion)regionLayers.get(selectedRegion.id)?.openPopup();
    }

    function commuteView(){
      const rule=data?.commute_rule||{};
      return `<section class="card insight-panel"><div class="insight-heading"><h3>通勤自动标注</h3><span class="insight-badge">${rule.deleted?'已删除':rule.enabled?'运行中':rule.revision?'已暂停':'未设置'}</span></div>
        <p class="insight-note">在地图上选家和公司。新行程首次读取标签月份时，可信起止位置分别进入两个圆形范围，就自动标“通勤”；返程也匹配。位置采样可能有误差。</p>
        <div class="ledger-form"><label>家范围半径（米）<input id="commute-home-radius" aria-label="家范围半径" type="number" min="100" max="1000" step="50" value="${esc(commuteDraft.homeRadius)}"></label><label>公司范围半径（米）<input id="commute-work-radius" aria-label="公司范围半径" type="number" min="100" max="1000" step="50" value="${esc(commuteDraft.workRadius)}"></label></div>
        <p class="insight-note">家：${commuteDraft.home?'已选点':'未选点'} · 公司：${commuteDraft.work?'已选点':'未选点'}。范围可在地图上查看后调整。</p>
        <div class="insight-actions">${button(commuteShown?'隐藏选点地图':'打开选点地图','commute-map')}${button('保存通勤规则','commute-save',!owner||!data||!commuteDraft.home||!commuteDraft.work||commuteBusy)}${rule.revision&&!rule.deleted?button(rule.enabled?'暂停自动标注':'恢复自动标注',rule.enabled?'commute-pause':'commute-resume',commuteBusy):''}${rule.revision&&!rule.deleted?button('删除通勤规则','commute-delete',commuteBusy):''}</div>
        ${commuteShown?`<div class="insight-actions"><button class="button secondary" data-tag="commute-place-home" aria-pressed="${placeMode==='home'}">选择家地点</button><button class="button secondary" data-tag="commute-place-work" aria-pressed="${placeMode==='work'}">选择公司地点</button>${button('将地图中心设为家','commute-center-home')}${button('将地图中心设为公司','commute-center-work')}</div><div id="commute-map" aria-label="通勤地点选点地图"></div><p class="insight-note">${placeMode?`点击地图放置${placeMode==='home'?'家':'公司'}地点。放置后退出选点，再次修改请重新按“选择地点”。`:'选点已结束。要修改地点，请先按“选择家地点”或“选择公司地点”。'}也可拖动标记调整中心；键盘可平移地图，再用“将地图中心设为”按钮选点。圆圈是当前匹配边界。</p>`:''}</section>`;
    }
    function paintCommuteMap(){
      const el=node?.querySelector('#commute-map');if(!el||commuteMap)return;
      commuteMap=AmapMaps.createMap(el,{scrollWheelZoom:false});
      AmapMaps.addTiles(commuteMap);
      const points=[commuteDraft.home,commuteDraft.work].filter(Boolean);
      if(points.length===2)commuteMap.fitBounds(points.map(p=>[p.latitude,p.longitude]),{padding:[45,45],maxZoom:15});
      else if(points.length)commuteMap.setView([points[0].latitude,points[0].longitude],14);
      else commuteMap.setView([35,105],4);
      for(const [key,color] of [['home','#20776e'],['work','#bd5a32']]){
        const point=commuteDraft[key];if(!point)continue;
        const center=[point.latitude,point.longitude];
        L.circle(center,{radius:commuteDraft[key+'Radius'],color,fillOpacity:.12}).addTo(commuteMap);
        const icon=L.divIcon({className:`commute-pin commute-pin-${key}`,html:`<span>${key==='home'?'家':'公司'}</span>`,iconSize:[38,38],iconAnchor:[19,19]});
        L.marker(center,{draggable:true,icon,title:key==='home'?'家地点':'公司地点'}).addTo(commuteMap).bindTooltip(key==='home'?'家':'公司').on('dragend',event=>{
          const where=event.target.getLatLng();commuteDraft[key]={latitude:where.lat,longitude:where.lng};commuteDirty=true;placeMode=null;commuteMap.remove();commuteMap=null;paint();
        });
      }
      commuteMap.on('click',event=>{if(!placeMode)return;commuteDraft[placeMode]={latitude:event.latlng.lat,longitude:event.latlng.lng};commuteDirty=true;placeMode=null;commuteMap.remove();commuteMap=null;paint();});
    }
    function routeView(){
      if(!selected)return '';
      return `<div id="tag-route" class="tag-route"><div class="insight-actions">${routeShown?button('隐藏路线小地图','hide-route'):button('查看路线小地图','show-route')}</div>${routeShown?`${routeBusy?'<p role="status">正在读取本趟路线…</p>':''}${routeError?`<p role="alert" class="notice error">${esc(routeError)}</p>`:''}${routeData?'<div id="tag-route-map" aria-label="本趟采样路线小地图"></div><p class="insight-note">仅连接可信采样点；首末点不一定是真实出发地和目的地。稀疏连线不代表实际道路。</p>':''}`:'<p class="insight-note">位置默认隐藏。点击后才读取本趟采样并加载地图底图。</p>'}</div>`;
    }
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      if(nameMap)nameViewport={center:nameMap.getCenter(),zoom:nameMap.getZoom()};nameMap?.remove();nameMap=null;
      routeMap?.remove();routeMap=null;commuteMap?.remove();commuteMap=null;if(placesMap)placesViewport={center:placesMap.getCenter(),zoom:placesMap.getZoom()};placesMap?.remove();placesMap=null;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">行程标签</span><h2>同类行程，放在一起看</h2><p>通勤、接娃、周末出游，让每趟记录有自己的分类。</p></div><span class="insight-source">自定义标签 · 同类比较</span></section>
        ${commuteView()}<section class="card insight-panel"><div class="insight-toolbar"><label>标签月份<input id="tag-month" type="month" aria-label="标签月份" value="${esc(month)}"></label>${button('读取行程标签','load',!owner||!month||loading)}${button('撤销标签操作','undo',!data?.can_undo)}</div>${loading?'<p role="status">正在读取…</p>':''}${status?`<p role="status" class="insight-note">${esc(status)}</p>`:''}${error?`<p role="alert" class="notice error">${esc(error)}</p>`:''}${data?`<p class="insight-note">${data.window.start_date} — ${data.window.end_date} · 按行程结束日期归期，${data.events.length} 条行程，${data.untagged_count} 条未贴标签。一趟可有多个标签，同组结果不能相加当总量。</p>`:''}${!owner?'<p>连接车辆账号并取得当前车辆绑定后，可管理标签。</p>':''}</section>
        ${placesView()}${selected?`<section class="card insight-panel"><div class="insight-heading"><h3>标注这趟行程</h3>${button('取消标注','cancel')}</div><p>${esc(time(selected.start_time))} → ${esc(time(selected.end_time))}<br>${number(selected.distance_km)} km · ${number(selected.duration_seconds===null?null:selected.duration_seconds/60)} 分钟 · ${selected.partial?'观测片段':'完整记录'}</p>${selected.automatic_commute?`<p class="insight-note">本趟“通勤”为自动标注；手工标签可另行编辑。</p>${button('取消本趟自动通勤','commute-exclude',false,`data-id="${esc(selected.id)}"`)}`:selected.commute_excluded?button('恢复本趟自动通勤','commute-include',false,`data-id="${esc(selected.id)}"`):''}${routeView()}<form id="tag-form" class="ledger-form" novalidate><div class="ledger-wide"><strong>点选已有标签</strong><div class="tag-quick-list">${(data?.suggested_tags||[]).map(tag=>`<button type="button" class="tag-quick" data-tag="toggle-label" data-label="${esc(tag)}" aria-label="${labelList().includes(tag)?'取消':'选择'}标签 ${esc(tag)}" aria-pressed="${labelList().includes(tag)}" ${busy?'disabled':''}>${esc(tag)}</button>`).join('')||'<span class="insight-note">还没有已有标签，可在下方输入新标签。</span>'}</div></div><label class="ledger-wide">行程标签（逗号分隔）<input id="tag-labels" aria-label="行程标签（逗号分隔）" type="text" maxlength="300" value="${esc(tags)}" ${busy?'disabled':''}></label><label class="ledger-wide">行程备注<textarea id="tag-note" aria-label="行程备注" maxlength="1000" rows="3" ${busy?'disabled':''}>${esc(note)}</textarea></label></form><p class="insight-note">可用中文或英文逗号分隔，每趟最多 10 个标签，每个 24 字。留空可清除标签；备注单独保留。</p><div class="insight-actions">${button('保存行程标签','save',loading)}</div></section>`:''}
        ${data?`<section class="card insight-panel"><div class="insight-heading"><h3>同类比较</h3><span class="insight-badge">${data.groups.length} 类标签</span></div>${data.groups.length?`<div class="ledger-form"><label>比较标签 A<select id="tag-group-a" aria-label="比较标签 A">${options(groupA)}</select></label><label>比较标签 B<select id="tag-group-b" aria-label="比较标签 B">${options(groupB)}</select></label></div>`:'<p class="insight-empty">从下方选择行程添加标签，即可比较。</p>'}<div id="tag-comparison"></div><p class="insight-note">完整与片段均按有效观测计入，每项单列样本数；均值表示每条记录的观测值，不代表完整行程均值。SOC 回升不算负耗电。百公里估算使用同一批至少 10 km、SOC 下降至少 3 个百分点且电量可估算的记录，按总估算电量 ÷ 总里程计算。SOC 电量不是电表计量。</p><p class="insight-note">距离、时长、样本量不同都可能影响结果。没有天气、路况或驾驶方式证据，不据此归因或排名。</p></section>
        <section class="card insight-panel"><div class="insight-heading"><h3>本月行程</h3><div class="insight-toolbar"><label>筛选标签<select id="tag-filter" aria-label="筛选标签"><option value="">全部标签与未标注</option><option value="untagged" ${filter==='untagged'?'selected':''}>未标注</option>${filterOptions()}</select></label><label>标签行程完整性<select id="tag-completeness" aria-label="标签行程完整性">${[['all','全部记录'],['complete','完整记录'],['partial','仅片段']].map(([key,label])=>`<option value="${key}" ${key===completeness?'selected':''}>${label}</option>`).join('')}</select></label></div></div><div id="tag-events"></div></section><div id="tag-trash"></div>`:''}`;
      paintGroups();paintEvents();paintRoute();paintCommuteMap();paintPlacesMap();paintNameMap();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function paintGroups(){
      const el=node?.querySelector('#tag-comparison');if(!data||!el)return;
      const metric=(label,value,unit,divisor=1)=>`<div><strong>${label}</strong><span>均值 ${number(value.mean===null?null:value.mean/divisor)} ${unit} · 中位 ${number(value.median===null?null:value.median/divisor)} ${unit}</span><span>范围 ${number(value.minimum===null?null:value.minimum/divisor)}–${number(value.maximum===null?null:value.maximum/divisor)} ${unit} · ${value.samples} 个有效样本</span></div>`;
      el.innerHTML=`<div class="tag-comparison">${[groupA,groupB].map((tag,i)=>{
        const g=data.groups.find(g=>g.tag===tag);if(!g)return '';
        return `<article><h4>${i?'B':'A'} · ${esc(tag)}</h4><p>${g.count} 条记录 · 完整 ${g.complete_count} · 片段 ${g.partial_count}</p>${metric('已观测里程',g.distance_km,'km')}${metric('观测时段',g.duration_seconds,'分钟',60)}${metric('观测 SOC 下降',g.soc_consumed,'百分点')}${metric('SOC 电量估算',g.estimated_kwh,'kWh')}<div><strong>百公里电量估算</strong><span>${number(g.efficiency.value)} kWh/100km</span><span>${g.efficiency.samples} 个有效样本 · 合计 ${number(g.efficiency.distance_km)} km</span></div></article>`;
      }).join('')}</div>`;
    }
    function paintRoute(){
      const el=node?.querySelector('#tag-route-map');if(!el||!routeData)return;
      const points=(routeData.observations||[]).filter(p=>p.trusted===true&&p.plottable===true&&Number.isFinite(p.latitude)&&Number.isFinite(p.longitude));
      if(!points.length){el.textContent='本趟暂无位置采样，无法绘制路线。';return;}
      routeMap=AmapMaps.createMap(el,{zoomControl:false,scrollWheelZoom:false});
      AmapMaps.addTiles(routeMap);
      const layer=L.layerGroup().addTo(routeMap);
      const density=RouteQuality.analyze(routeData.observations||[],routeData.segments||[],'state_time');
      density.parts.forEach(part=>L.polyline(part.points.map(p=>[p.latitude,p.longitude]),RouteQuality.lineOptions(part)).addTo(layer));
      for(const [point,label] of [[points[0],'首个采样点'],[points.at(-1),'末个采样点']])
        L.circleMarker([point.latitude,point.longitude],{radius:6,color:'#20776e',fillOpacity:1}).addTo(layer).bindTooltip(label);
      const bounds=points.map(p=>[p.latitude,p.longitude]);
      if(bounds.length===1)routeMap.setView(bounds[0],14);
      else routeMap.fitBounds(bounds,{padding:[24,24],maxZoom:15});
    }
    async function loadRoute(){
      if(!selected||routeShown)return;
      const identity=owner,eventId=selected.id,token=++routeSerial;
      routeShown=routeBusy=true;routeData=null;routeError='';paint();
      try{
        const result=await request(`/api/tracks?date=${encodeURIComponent(tripDate(selected.end_time))}&trip=${encodeURIComponent(eventId)}`);
        if(token!==routeSerial||owner!==identity||context()!==identity||selected?.id!==eventId)return;
        routeData=result;
      }catch(failure){if(token===routeSerial&&owner===identity&&selected?.id===eventId)routeError=failure.message;}
      finally{if(token===routeSerial&&owner===identity&&selected?.id===eventId){routeBusy=false;paint();}}
    }
    function paintEvents(){
      const el=node?.querySelector('#tag-events');if(!el||!data)return;
      const rows=data.events.filter(r=>(!filter||(filter==='untagged'?!r.tags.length:r.tags.includes(filter.slice(4))))&&(completeness==='all'||r.partial===(completeness==='partial')));
      const pages=Math.max(1,Math.ceil(rows.length/10));page=Math.max(0,Math.min(page,pages-1));
      el.innerHTML=(rows.slice(page*10,page*10+10).map(r=>`<article class="rule-record" data-tag-event="${esc(r.id)}"><div class="insight-heading"><h4>${esc(time(r.end_time))}</h4><span class="insight-badge">${r.partial?'观测片段':'完整记录'}</span></div><div class="tag-trip-facts"><span>开始<strong>${esc(time(r.start_time))}</strong></span><span>结束<strong>${esc(time(r.end_time))}</strong></span><span>里程<strong>${number(r.distance_km)} km</strong></span><span>时长<strong>${number(r.duration_seconds===null?null:r.duration_seconds/60)} 分钟</strong></span></div><p class="insight-note">参考地点：${placeLink(r.start_place)} → ${placeLink(r.end_place)}</p><p>SOC ${number(r.start_soc)}% → ${number(r.end_soc)}% · 电量估算 ${number(r.estimated_kwh)} kWh</p><div class="insight-badges">${r.tags.map(tag=>`<span class="insight-badge">${esc(tag)}${tag==='通勤'&&r.automatic_commute?' · 自动':''}</span>`).join('')||'<span class="insight-note">未贴标签</span>'}</div>${r.commute_reason==='insufficient'?'<p class="insight-note">起止位置证据不足，未自动判定通勤。</p>':''}${r.note?`<p class="ledger-note">${esc(r.note)}</p>`:''}<div class="insight-actions">${button('标注这趟行程','edit',false,`data-id="${esc(r.id)}"`)}${r.annotation_id?button('删除行程标签','delete',false,`data-id="${esc(r.annotation_id)}"`):''}</div></article>`).join('')||'<p class="insight-empty">本月没有符合筛选的行程</p>')+`<div class="insight-pagination">${button('上一页标签行程','previous',page===0)}<span>${rows.length} 条 · ${page+1} / ${pages}</span>${button('下一页标签行程','next',page+1===pages)}</div>`;
      const trashPages=Math.max(1,Math.ceil(data.trash.length/10));trashPage=Math.min(trashPage,trashPages-1);
      node.querySelector('#tag-trash').innerHTML=data.trash.length?`<section class="card insight-panel"><h3>已删除的行程标签</h3><div class="ledger-trash-list">${data.trash.slice(trashPage*10,trashPage*10+10).map(r=>`<div><span>${esc(time(r.end_time))} · ${esc(r.tags.join('、')||'无标签')}</span>${button('恢复行程标签','restore',false,`data-id="${esc(r.id)}"`)}</div>`).join('')}</div><div class="insight-pagination">${button('上一页删除标签','trash-previous',trashPage===0)}<span>${trashPage+1} / ${trashPages}</span>${button('下一页删除标签','trash-next',trashPage+1===trashPages)}</div></section>`:'';
    }
    async function load(preservePages=false){
      if(!owner||!month)return false;
      const token=++serial,identity=owner;attempted=true;loading=true;error='';paint();
      try{const result=await request('/api/insights/trip-tags?date='+encodeURIComponent(month+'-01'));
        if(!valid(token,serial,identity))return false;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=result;if(!preservePages)page=trashPage=0;syncCommuteRule();
        if(selected){selected=data.events.find(row=>row.id===selected.id)||null;if(!selected)closeRoute();}
        if(!data.groups.some(g=>g.tag===groupA))groupA=data.groups[0]?.tag||'';
        if(!data.groups.some(g=>g.tag===groupB))groupB=data.groups[1]?.tag||data.groups[0]?.tag||'';
        if(filter&&filter!=='untagged'&&!data.groups.some(g=>'tag:'+g.tag===filter))filter='';return true;
      }catch(failure){if(valid(token,serial,identity))error=failure.message;return false;}
      finally{if(valid(token,serial,identity)){loading=false;paint();}}
    }
    async function mutate(action,id){
      if(busy||loading||!data||action==='save'&&!selected)return;
      const token=++writeSerial,identity=owner,payload={action,id,revision:data.revision,context:owner};
      if(action==='save')Object.assign(payload,{id:selected.annotation_id,event_id:selected.id,tags:tags.split(/[,，\n]/).map(s=>s.trim()).filter(Boolean),note});
      busy=true;error='';status='';paint();
      try{const result=await request('/api/insights/trip-tags',payload);if(!valid(token,writeSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data.revision=result.revision;data.can_undo=result.can_undo;status='行程标签操作已保存。';
        if(action==='delete'&&selected?.annotation_id===id){selected=null;tags=note='';closeRoute();}
        if(!await load()&&valid(token,writeSerial,identity))status+=' 列表尚未刷新，请重新读取核对。';
      }catch(failure){if(valid(token,writeSerial,identity))error=failure.message+' 填写内容保留；请重新读取核对后操作。';}
      finally{if(valid(token,writeSerial,identity)){busy=false;paint();}}
    }
    async function mutatePlaceName(action){
      if(busy||loading||!data||!namePlace&&action!=='place-name-undo')return;
      const identity=owner,token=++writeSerial;
      const payload={action,date:month+'-01',place_id:namePlace?.id,place_key:namePlace?.name_key,region_id:namePlace?.region_id,name:nameDraft,radius_m:nameRadius,shape:nameShape,vertices:nameShape==='polygon'?nameVertices:undefined,preview_token:namePreview?.preview_token,revision:data.place_statistics.name_revision,context:owner};
      busy=true;error='';status='';paint();
      try{
        const result=await request('/api/insights/trip-tags',payload);
        if(!valid(token,writeSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        if(action==='place-name-preview'){namePreview=result;return;}
        data.place_statistics.name_revision=result.name_revision;closeNameEditor();status=action==='place-name-undo'?'已撤销地点操作。':'地点名称已保存。';
        if(!await load()&&valid(token,writeSerial,identity))status+=' 列表尚未刷新，请重新读取核对。';
      }catch(failure){if(valid(token,writeSerial,identity))error=failure.message+' 名称草稿保留；请重新读取后再保存。';}
      finally{if(valid(token,writeSerial,identity)){busy=false;paint();}}
    }
    async function mutateCommute(action,eventId){
      if(commuteBusy||busy||!owner||!data)return;
      const identity=owner,token=++writeSerial;
      const payload={action,context:owner,revision:data.commute_rule?.revision||0};
      if(action==='commute-save'){
        const {home,work,homeRadius,workRadius}=commuteDraft;
        if(!home||!work||![homeRadius,workRadius].every(v=>Number.isInteger(v)&&v>=100&&v<=1000)){
          error='请选好两个地点，并将半径设为 100–1000 米。';paint();return;
        }
        payload.home={...home,radius_m:homeRadius};payload.work={...work,radius_m:workRadius};
      }
      if(eventId)payload.event_id=eventId;
      commuteBusy=true;error=status='';paint();
      try{
        const result=await request('/api/insights/trip-tags',payload);
        if(!valid(token,writeSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        if(action==='commute-save')commuteDirty=false;
        status=action==='commute-exclude'?'已取消本趟自动通勤。':action==='commute-include'?'已恢复本趟自动通勤。':'通勤设置已保存。';await load();
      }catch(failure){if(valid(token,writeSerial,identity))error=failure.message+' 当前设置已保留。';}
      finally{if(valid(token,writeSerial,identity)){commuteBusy=false;paint();}}
    }
    let tripRevision;
    function mount(container){
      const contextChanged=owner!==context(),recordsChanged=!busy&&tripRevision!==getState()?.trip_records_revision,remount=node!==container;node=container;
      if(contextChanged||recordsChanged)tripRevision=getState()?.trip_records_revision;
      if(contextChanged){owner=context();data=null;selected=null;tags=note='';attempted=false;loading=busy=false;serial++;writeSerial++;error=status='';filter=groupA=groupB='';closeRoute();closePlacesMap();closeCommuteMap();commuteDraft={home:null,work:null,homeRadius:300,workRadius:300};commuteDirty=false;}
      else if(recordsChanged&&attempted){
        if(selected||namePlace||commuteDirty){serial++;loading=false;status='行程记录已变化；填写内容保留，请重新读取核对后再保存。';}
        else load(true);
      }
      if(contextChanged||remount||recordsChanged)paint();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;const el=event.target;
      if((event.type==='input'||event.type==='change')&&el.id==='tag-month'){if(month===el.value)return true;month=el.value;serial++;writeSerial++;loading=busy=false;data=selected=null;tags=note=error='';status='日期已修改，请重新读取行程标签。';page=trashPage=0;filter=groupA=groupB='';closeRoute();closeCommuteMap();closePlacesMap();paint();return true;}
      if(event.type==='input'&&el.id==='tag-place-name'){nameDraft=el.value;namePreview=null;node.querySelector('[data-tag="place-name-save"]')?.setAttribute('disabled','');node.querySelector('#tag-name-preview')?.remove();return true;}
      if(event.type==='input'&&el.id==='tag-labels'){tags=el.value;syncQuickLabels();return true;}
      if(event.type==='input'&&el.id==='tag-note'){note=el.value;return true;}
      if(event.type==='input'&&['commute-home-radius','commute-work-radius'].includes(el.id)){
        commuteDraft[el.id==='commute-home-radius'?'homeRadius':'workRadius']=Number(el.value);commuteDirty=true;
        if(commuteMap){commuteMap.remove();commuteMap=null;paintCommuteMap();}return true;
      }
      if(event.type==='change'){
        if(el.id==='tag-name-shape'){nameShape=el.value;nameDrawing=nameShape==='polygon'&&nameVertices.length<3;invalidateName();paint();return true;}
        if(el.id==='tag-region-method'){nameFreehand=el.value==='freehand';nameDrawing=nameFreehand||nameVertices.length<3;invalidateName();paint();return true;}
        if(el.id==='tag-region-vertex'){nameVertex=el.value===''?null:Number(el.value);paint();return true;}
        if(el.id==='tag-name-radius'){nameRadius=Number(el.value);namePreview=null;paint();return true;}
        if(el.id==='tag-group-a'){groupA=el.value;paintGroups();return true;}
        if(el.id==='tag-group-b'){groupB=el.value;paintGroups();return true;}
        if(el.id==='tag-filter'){filter=el.value;page=0;paintEvents();return true;}
        if(el.id==='tag-completeness'){completeness=el.value;page=0;paintEvents();return true;}
      }
      if(event.type!=='click')return false;
      const target=el.closest('[data-tag]');if(!target||target.disabled)return false;
      const action=target.dataset.tag,id=target.dataset.id;
      if(action==='place-name-edit'){openNameEditor(data.place_statistics.places.find(p=>p.id===id));return true;}
      if(action==='region-edit'){
        const r=data.place_statistics.name_regions.find(r=>r.id===id);
        openNameEditor({label:r.name,name_source:'manual',region_id:r.id,manual_name_id:r.id,latitude:r.latitude,longitude:r.longitude,name_shape:r.shape||'circle',name_vertices:r.vertices,name_radius_m:r.radius_m});return true;
      }
      if(action==='region-new'){closeNameEditor();namePlace={label:'新建地点区域',isNew:true};nameShape='polygon';nameDrawing=true;nameFreehand=true;paint();node.querySelector('#tag-place-name')?.focus({preventScroll:true});return true;}
      if(action==='region-freehand'||action==='region-browse'){nameDrawing=action==='region-freehand';if(nameDrawing)nameFreehand=true;invalidateName();paint();return true;}
      if(action==='region-finish'||action==='region-draw'){nameDrawing=action==='region-draw';invalidateName();paint();return true;}
      if(action==='region-reset'){nameVertices=[];nameVertex=null;nameDrawing=true;invalidateName();paint();return true;}
      if(action==='region-pop'||action==='region-delete-vertex'){
        if(action==='region-pop')nameVertices.pop();else if(nameVertex!==null)nameVertices.splice(nameVertex,1);
        nameVertex=null;if(nameVertices.length<3)nameDrawing=true;invalidateName();paint();return true;
      }
      if(action==='region-add-center'){const point=nameMap?.getCenter();if(point&&nameDrawing&&nameVertices.length<100){nameVertices.push([point.lat,point.lng]);nameVertex=nameVertices.length-1;invalidateName();paint();}return true;}
      if(action==='place-name-cancel'){closeNameEditor();paint();return true;}
      if(['place-name-save','place-name-clear','place-name-preview','place-name-undo'].includes(action)){mutatePlaceName(action);return true;}
      if(action==='place-focus'){focusPlace(id);return true;}
      if(action==='region-focus'){focusPlace(id,true);return true;}
      if(action==='places-all'){focusedPlace=focusedRegion=placesViewport=null;placesMap?.remove();placesMap=null;paint();return true;}
      if(action==='places-map'){placesShown=!placesShown;if(!placesShown){focusedPlace=focusedRegion=placesViewport=null;placesMap?.remove();placesMap=null;}paint();return true;}
      if(action==='places-previous'||action==='places-next'){placePage+=action==='places-next'?1:-1;paint();return true;}
      if(action==='commute-map'){commuteShown=!commuteShown;placeMode=commuteShown&&!commuteDraft.home?'home':null;paint();return true;}
      if(action==='commute-place-home'||action==='commute-place-work'){const key=action.endsWith('home')?'home':'work';placeMode=placeMode===key?null:key;paint();return true;}
      if(action==='commute-center-home'||action==='commute-center-work'){
        const where=commuteMap?.getCenter(),key=action.endsWith('home')?'home':'work';
        if(where){commuteDraft[key]={latitude:where.lat,longitude:where.lng};commuteDirty=true;placeMode=null;paint();}return true;
      }
      if(action.startsWith('commute-')){mutateCommute(action,id);return true;}
      if(action==='load')load();
      else if(action==='edit'){closeRoute();selected=data.events.find(r=>r.id===id);tags=(selected.manual_tags||selected.tags).join(', ');note=selected.note;error='';paint();node.querySelector('#tag-form').scrollIntoView({block:'start'});}
      else if(action==='cancel'){selected=null;tags=note='';closeRoute();paint();}
      else if(action==='show-route')loadRoute();
      else if(action==='hide-route'){closeRoute();paint();}
      else if(action==='toggle-label'){
        const labels=labelList(),label=target.dataset.label,index=labels.indexOf(label);
        if(index<0)labels.push(label);else labels.splice(index,1);
        tags=labels.join(', ');paint();
      }
      else if(action==='previous'){page--;paintEvents();}else if(action==='next'){page++;paintEvents();}
      else if(action==='trash-previous'){trashPage--;paintEvents();}else if(action==='trash-next'){trashPage++;paintEvents();}
      else mutate(action,id);return true;
    }
    return {mount,handle};
  }
  root.TripTagsPage={create,freehandVertices};
})(window);
