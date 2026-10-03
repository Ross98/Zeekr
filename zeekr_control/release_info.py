"""Deployment-authored version metadata, checked against the running files."""
import argparse
import hashlib
import json
from pathlib import Path
import re

FEATURES={
 'calendar-review':dict(label='日历用车回顾与充电对账',files=['zeekr_control/usage_calendar.py','zeekr_control/static/usage-calendar.js','zeekr_control/static/insights.css','zeekr_control/static/navigation-state.js','zeekr_control/static/app.js','zeekr_control/web.py']),
 'overview-layout':dict(label='桌面总览与记录待办',files=['zeekr_control/web.py','zeekr_control/static/overview-dashboard.js','zeekr_control/static/app.js','zeekr_control/static/app.css','zeekr_control/static/index.html']),
 'notification-brief':dict(label='行程与充电通知精简',files=['zeekr_control/report_render.py']),
 'tyre-alerts':dict(label='胎压异常通知',files=['zeekr_control/tyre_notifications.py','zeekr_control/monitor_runtime.py','zeekr_control/personal_store.py','zeekr_control/web.py','zeekr_control/static/custom-reminders.js']),
 'charging-readability':dict(label='充电图表可读性',files=['zeekr_control/static/app.js','zeekr_control/static/app.css','zeekr_control/static/theme.css']),
 'home-attention':dict(label='首页异常提示',files=['zeekr_control/static/app.js','zeekr_control/static/app.css']),
 'pending-ledger':dict(label='充电待补账',files=['zeekr_control/static/charge-ledger.js','zeekr_control/static/app.css']),
 'place-names':dict(label='地点命名与范围预览',files=['zeekr_control/trip_place_names.py','zeekr_control/trip_places.py','zeekr_control/trip_tags.py','zeekr_control/static/trip-tags.js','zeekr_control/static/insights.css']),
 'travel-insights':dict(label='路线对比与用车回顾',files=['zeekr_control/travel_insights.py','zeekr_control/static/travel-insights.js','zeekr_control/static/insights.js','zeekr_control/web.py','zeekr_control/static/index.html','zeekr_control/static/insights.css']),
 'url-navigation':dict(label='URL 导航恢复',files=['zeekr_control/static/navigation-state.js','zeekr_control/static/app.js','zeekr_control/static/insights.js','zeekr_control/static/index.html']),
 'release-summary':dict(label='实际发布版本摘要',files=['zeekr_control/release_info.py','zeekr_control/web.py','zeekr_control/static/app.js']),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_release(root=None):
    root=Path(root) if root is not None else Path(__file__).resolve().parent.parent
    unknown=dict(status='unrecorded',base_version=None,features=[])
    path=root/'release-manifest.json'
    if not path.exists():return unknown
    try:
        if path.stat().st_size>65536 or path.is_symlink():raise ValueError()
        manifest=json.loads(path.read_text(encoding='utf-8'))
        base=manifest['base_version'];entries=manifest['features']
        if not isinstance(base,str) or not re.fullmatch('[0-9a-f]{40}',base) or not isinstance(entries,dict) or set(entries)-set(FEATURES):raise ValueError()
        features=[]
        for key,hashes in entries.items():
            config=FEATURES[key]
            if not isinstance(hashes,dict) or set(hashes)!=set(config['files']) or any(not isinstance(h,str) or not re.fullmatch('[0-9a-f]{64}',h) for h in hashes.values()):raise ValueError()
            matched=all((root/file).is_file() and digest(root/file)==value for file,value in hashes.items())
            features.append(dict(id=key,label=config['label'],status='matched' if matched else 'mismatch'))
        return dict(status='recorded',base_version=base,features=features)
    except (OSError,ValueError,KeyError,TypeError):return dict(unknown,status='invalid')


def write_manifest(root,base,features):
    if not re.fullmatch('[0-9a-f]{40}',base) or not features or set(features)-set(FEATURES):raise ValueError('基础版本或功能范围无效。')
    root=Path(root)
    manifest=dict(base_version=base,features={key:{file:digest(root/file) for file in FEATURES[key]['files']} for key in features})
    temporary=root/'release-manifest.json.tmp'
    temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(root/'release-manifest.json')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='在候选发布目录生成实际功能清单；不会部署。')
    parser.add_argument('--root',required=True);parser.add_argument('--base',required=True)
    parser.add_argument('--feature',action='append',choices=sorted(FEATURES),required=True)
    args=parser.parse_args();write_manifest(args.root,args.base,args.feature)
