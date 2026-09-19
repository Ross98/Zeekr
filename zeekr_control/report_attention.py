"""Freeze conservative status explanations; pending reverse enums never alert."""


def build(kind, end, parking, created_at):
    current = parking if kind == 'trip_end' and parking else end
    age = created_at - current.get('state_time') if current and current.get('state_time') is not None else None
    fresh = age is not None and -30000 <= age <= 180000
    items = []
    if not current:
        items.append({'level': 'unknown', 'key': 'parking', 'text': '未取得更新停车状态'})
    else:
        if current.get('locked') is not True:
            items.append({'level': 'unknown', 'key': 'lock', 'text': '锁车状态未确认'})
        for key, noun in (('doors', '车门'), ('windows', '车窗')):
            values = current.get('closures', {}).get(key, [])
            if not values or any(value != 'closed' for value in values):
                items.append({'level': 'unknown', 'key': key, 'text': noun + '状态未全部确认'})
        if current.get('trunk') != 'closed':
            items.append({'level': 'unknown', 'key': 'trunk', 'text': '尾门状态未确认'})
        if not fresh:
            items.append({'level': 'unknown', 'key': 'stale', 'text': '状态观测已陈旧'})
        if current.get('dc_lid') == 'open':
            items.append({'level': 'status', 'key': 'dc_lid', 'text': '直流口盖打开'})
    changes = []
    if kind == 'trip_end' and end and parking and parking.get('state_time') != end.get('state_time'):
        if end.get('locked') is not True and parking.get('locked') is True:
            changes.append({'key':'lock','time':parking.get('state_time'),'text':'后续观测已确认锁车'})
        for key,noun in (('doors','车门'),('windows','车窗')):
            before,end_values = end.get('closures',{}).get(key,[]),parking.get('closures',{}).get(key,[])
            if before and end_values and not all(x=='closed' for x in before) and all(x=='closed' for x in end_values):
                changes.append({'key':key,'time':parking.get('state_time'),'text':'后续观测已确认%s关闭' % noun})
    return {'version': 'attention-v1', 'reference_time': created_at, 'fresh': fresh,
            'items': items, 'pinned': [], 'changes': changes,
            'pending_capabilities': ['unlocked', 'openings', 'connector_state', 'tyre_alert', 'stop_reason']}
