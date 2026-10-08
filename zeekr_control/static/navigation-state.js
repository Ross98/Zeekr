(function(root){
  'use strict';
  const pages=['overview','calendar','report','car','energy','books','tracks','fields','insights','settings','more'];
  const tasks=['records','ledger','charge-comparison','life','rules','quality','parameters','hypotheses','fields','research','automatic','lab','time','report','calendar','routes','review'];
  const date=value=>/^20\d{2}-\d{2}-\d{2}$/.test(value)&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
  const rules={step:v=>['overview','evidence','experiment','conclusion'].includes(v),p:v=>pages.includes(v)&&v!=='overview',t:v=>tasks.includes(v),s:v=>['local','cloud','tags'].includes(v),
    review:v=>v==='1',heat:v=>['distance','cost'].includes(v),year:v=>/^20\d{2}$/.test(v),record:v=>/^[A-Za-z0-9_:-]{1,256}$/.test(v),range:v=>['day','range'].includes(v),date,month:v=>/^20\d{2}-(0[1-9]|1[0-2])$/.test(v),start:date,end:date,view:v=>['distance','cost','pending','energy'].includes(v),period:v=>['week','month'].includes(v),q:v=>v==='1'};
  function clean(values){const result={};for(const [key,test] of Object.entries(rules)){const value=values[key];try{if(typeof value==='string'&&test(value))result[key]=value;}catch{}}return result;}
  function read(search){return clean(Object.fromEntries(new URLSearchParams(search)));}
  function encode(values){return new URLSearchParams(clean(values)).toString();}
  root.NavigationState={read,encode};

  // A repaint is one synchronous transaction. Restore only within the same
  // account/view; never schedule a scroll that can override the next user action.
  const scopes=new WeakMap();let depth=0;
  const attributes=el=>JSON.stringify(Object.entries(el.dataset).sort());
  const elementKey=el=>el.id?'id:'+el.id:JSON.stringify([
    el.parentElement?.closest('[id]')?.id,el.tagName,el.getAttribute('name'),el.className,attributes(el)]);
  function disclosures(container){
    const seen=new Map();
    return new Map([...container.querySelectorAll('details')].map(el=>{
      const summary=el.querySelector(':scope > summary');
      const text=[...(summary?.childNodes||[])].filter(n=>n.nodeType===3).map(n=>n.textContent).join('')||summary?.textContent||'';
      const label=text.split('·')[0].replace(/[\d.,]+/g,'#').replace(/\s+/g,' ').trim();
      const base=el.id?'id:'+el.id:el.dataset.detail?'detail:'+el.dataset.detail:
        JSON.stringify([el.parentElement?.closest('[id]')?.id,el.className,label]);
      const occurrence=seen.get(base)||0;seen.set(base,occurrence+1);
      return [base+':'+occurrence,el];
    }));
  }
  function preserve(container,draw){
    if(!container?.isConnected)return draw();
    const scope=root.RefreshView.context?.()||'',previous=scopes.get(container);
    if(depth){scopes.set(container,scope);return draw();}
    let saved;
    if(previous===undefined||previous===scope){
      const details=disclosures(container),focused=document.activeElement;
      const summaryKey=[...details].find(([,el])=>el.querySelector(':scope > summary')===focused)?.[0];
      saved={x:root.scrollX,y:root.scrollY,details:new Map([...details].map(([key,el])=>[key,el.open])),
        scrolls:new Map([...container.querySelectorAll('*')].filter(el=>el.scrollTop||el.scrollLeft)
          .map(el=>[elementKey(el),[el.scrollLeft,el.scrollTop]])),
        focus:container.contains(focused)?{key:elementKey(focused),summaryKey,
          start:focused.selectionStart,end:focused.selectionEnd,top:focused.getBoundingClientRect().top}:null};
    }
    depth++;
    try{return draw();}
    finally{
      depth--;scopes.set(container,scope);
      if(saved&&container.isConnected&&(root.RefreshView.context?.()||'')===scope){
        const details=disclosures(container);
        for(const [key,open] of saved.details){const el=details.get(key);if(el)el.open=open;}
        const elements=saved.scrolls.size||saved.focus?[...container.querySelectorAll('*')]:[];
        for(const el of elements){const scroll=saved.scrolls.get(elementKey(el));if(scroll){el.scrollLeft=scroll[0];el.scrollTop=scroll[1];}}
        let focusTarget;
        if(saved.focus){
          const target=saved.focus.summaryKey?details.get(saved.focus.summaryKey)?.querySelector(':scope > summary'):
            elements.find(el=>elementKey(el)===saved.focus.key);
          focusTarget=target;target?.focus({preventScroll:true});
          if(target&&typeof saved.focus.start==='number'&&(target.tagName==='TEXTAREA'||['text','search','url','tel','password'].includes(target.type)))
            target.setSelectionRange(saved.focus.start,saved.focus.end);
        }
        root.scrollTo({left:saved.x,top:saved.y,behavior:'instant'});
        if(focusTarget?.matches('input:not([type=date]):not([type=month]),textarea')){
          const delta=focusTarget.getBoundingClientRect().top-saved.focus.top;
          if(Math.abs(delta)>1)root.scrollBy({top:delta,behavior:'instant'});
        }
      }
    }
  }
  let intent=0;
  for(const type of ['wheel','touchmove','pointerdown','keydown'])
    root.addEventListener(type,event=>{if(event.isTrusted)intent++;},{passive:true,capture:true});
  root.addEventListener('pointermove',event=>{if(event.isTrusted&&event.buttons)intent++;},{passive:true,capture:true});
  function guard(callback){
    const captured=intent,scope=root.RefreshView.context?.()||'';
    return (...args)=>{if(captured===intent&&scope===(root.RefreshView.context?.()||''))return callback(...args);};
  }
  root.RefreshView={preserve,guard,context:null};
})(window);
