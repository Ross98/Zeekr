"""Frozen, privacy-projected observations. Never promote research to capabilities."""
import time
import uuid

from .personal_store import VALID_ID


def text_field(data,key,limit,required=False):
    value=data.get(key,'')
    if not isinstance(value,str) or len(value)>limit or required and not value.strip():
        raise ValueError('请填写实验名称、实际动作，并保持名称 80 字、动作 300 字、备注 2000 字以内。')
    return value.strip()


def warnings(before,after,action_at):
    result=[]
    if not before['observed_at']<=action_at<=after['observed_at']:result.append('action_not_bracketed')
    a,b=before['state_time'],after['state_time']
    if a is None or b is None:result.append('vehicle_time_unknown')
    elif b<=a:result.append('vehicle_time_not_advanced')
    if before['flags'] or after['flags']:result.append('flagged_samples')
    if after['observed_at']-before['observed_at']>600000:result.append('wide_sample_gap')
    return result


class ParameterExperiments:
    def __init__(self,store,archive,clock=None):
        self.store=store;self.archive=archive;self.clock=clock or (lambda:int(time.time()*1000))

    def detail(self,owner,vehicle,identity):
        if not isinstance(identity,str) or not VALID_ID.fullmatch(identity):raise ValueError('实验编号无效。')
        saved=self.store.read(owner,vehicle,'experiments')
        row=next((r for r in saved['records'] if r['id']==identity),None)
        if row is None:raise ValueError('实验不存在或不属于当前账号车辆。')
        return dict(row,revision=saved['revision'])

    def query(self,owner,vehicle):
        saved=self.store.read(owner,vehicle,'experiments')
        for row in saved['records']:
            body=row['body'];body['change_count']=len(body.pop('changes'))
        return saved

    def update(self,owner,vehicle,data,scope,guard=None):
        action=data.get('action');identity=data.get('id');body=None
        if action=='save':
            title=text_field(data,'title',80,True);description=text_field(data,'action_text',300,True)
            note=text_field(data,'note',2000);action_at=data.get('action_at')
            if type(action_at) is not int or not 0<action_at<=min(32503680000000,self.clock()+60000):
                raise ValueError('请填写已经发生的动作时间（北京时间）。')
            before,after=data.get('before'),data.get('after');paths=data.get('paths')
            if not isinstance(paths,list) or len(paths)>40 or any(not isinstance(p,str) for p in paths):
                raise ValueError('请从变化列表选择至多 40 个安全字段。')
            paths=list(dict.fromkeys(paths))
            if identity:
                existing=self.detail(owner,vehicle,identity)['body']
                if before!=existing['before']['key'] or after!=existing['after']['key'] or paths!=existing['paths']:
                    raise ValueError('保存后的样本与字段保留原记录；更换样本请新建实验。')
                body=dict(existing)
            else:
                if before==after:raise ValueError('请选择两条不同的前后观测。')
                compared=self.archive.compare(scope,vehicle,before,after)
                a,b=compared['before'],compared['after']
                if a['observed_at']>b['observed_at']:raise ValueError('前样本的采集时间不能晚于后样本。')
                allowed={field['path']:field for field in compared['changes']}
                if any(p not in allowed for p in paths):raise ValueError('只能保存发生变化的安全白名单字段。')
                changes=[]
                for path in paths:
                    field=allowed[path]
                    changes.append({**{key:field[key] for key in ('path','name','group','unit','display_limited')},
                                    **{side:{key:field[side][key] for key in ('raw','value','status')}
                                       for side in ('before','after')}})
                body=dict(before=a,after=b,paths=paths,changes=changes,compared_fields=compared['compared_fields'],
                          saved_at=self.clock(),status='research_only')
                identity='experiment_'+uuid.uuid4().hex
            body.update(title=title,action_text=description,action_at=action_at,note=note,
                        warnings=warnings(body['before'],body['after'],action_at))
        saved=self.store.change(owner,vehicle,'experiments',action,identity,body,data.get('revision'),guard=guard)
        return dict(id=identity,revision=saved['revision'],can_undo=saved['can_undo'])
