#!/usr/bin/env node
// Explicit manifests prevent older mixed mobile suites entering desktop checks.
const {spawnSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const groups={
  unit:['test_overview_dashboard','books_overview','navigation_state','theme','vehicle',
    'chart','route_quality','road_matching_display','amap_maps','charge_ledger_preview',
    'parking_calendar','parking_calendar_model','parking_manual_start','vehicle_life_history',
    'usage_report_analysis','test_freehand_regions','ui_field_review_rules'],
  smoke:['ui_smoke','ui_status_summary','ui_overview_dashboard'],
  review:['ui_review_fixes','ui_lazy_tools','ui_async_analysis','ui_overview_dashboard','ui_books_overview',
    'ui_books_navigation','ui_books_safety','ui_tool_navigation','ui_insights_navigation',
    'ui_parameter_flow','ui_parameter_workspace','ui_refresh_view','ui_refresh_scroll']
};
const group=process.argv[2]||'review';
if(group==='desktop')groups.desktop=[...new Set([...groups.smoke,...groups.review])];
const syntax=group==='syntax';
const files=syntax?fs.readdirSync(path.join(root,'zeekr_control/static'))
  .filter(name=>name.endsWith('.js')).map(name=>path.join('zeekr_control/static',name))
  :groups[group]?.map(name=>`tests/${name}.cjs`);
if(!files){console.error('Choose unit, smoke, review, desktop or syntax.');process.exit(2);}
const started=Date.now();
for(const file of files){
  console.log(`\n[${group}] ${file}`);
  const result=spawnSync(process.execPath,[...(syntax?['--check']:[]),file],{
    cwd:root,env:{...process.env,DESKTOP_ONLY:'1',PYTHONDONTWRITEBYTECODE:'1'},stdio:'inherit'
  });
  if(result.error||result.status!==0){
    if(result.error)console.error(result.error.message);
    process.exit(result.status||1);
  }
}
console.log(`\n${files.length} ${group} files passed in ${((Date.now()-started)/1000).toFixed(1)}s; desktop only.`);
