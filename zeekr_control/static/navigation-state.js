(function(root){
  'use strict';
  const pages=['overview','car','energy','map','tracks','fields','insights','settings','more'];
  const tasks=['records','ledger','charge-comparison','life','rules','quality','fields','research','automatic','lab','time','report','calendar','routes','review'];
  const date=value=>/^20\d{2}-\d{2}-\d{2}$/.test(value)&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
  const rules={p:v=>pages.includes(v)&&v!=='overview',t:v=>tasks.includes(v),s:v=>['local','cloud','tags'].includes(v),
    review:v=>v==='1',heat:v=>['distance','cost'].includes(v),year:v=>/^20\d{2}$/.test(v),record:v=>/^[A-Za-z0-9_:-]{1,256}$/.test(v),range:v=>['day','range'].includes(v),date,month:v=>/^20\d{2}-(0[1-9]|1[0-2])$/.test(v),start:date,end:date,view:v=>['distance','cost','pending','energy'].includes(v),period:v=>['week','month'].includes(v),q:v=>v==='1'};
  function clean(values){const result={};for(const [key,test] of Object.entries(rules)){const value=values[key];try{if(typeof value==='string'&&test(value))result[key]=value;}catch{}}return result;}
  function read(search){return clean(Object.fromEntries(new URLSearchParams(search)));}
  function encode(values){return new URLSearchParams(clean(values)).toString();}
  root.NavigationState={read,encode};
})(window);
