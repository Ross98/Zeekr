"""Explicit local Keychain enrollment and one authorized refresh validation.

Never prints account identifiers, credentials, raw responses or verification
codes. No refresh replay after an ambiguous result. Auto mode stays disabled.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid
from .client import Client
from .credential_coordinator import CredentialCoordinator,CredentialBusy,refresh_fingerprint
from .credential_store import credential_store,sync_directory
from .errors import ApiError,RequestDeferred
from .query_policy import QueryPolicy
from .refresh_recovery import RefreshDriver,RefreshPolicy
from .snapshots import session_scope
from .storage import load,save as atomic_save


def save(path,value):
    atomic_save(path,value);sync_directory(path.parent)


def configure(path):
    if sys.platform!='darwin':raise ApiError('钥匙串配置只适用于 macOS。')
    coordinator=CredentialCoordinator(path)
    with coordinator.locked() as db:
        if db.execute('SELECT 1 FROM credential_operations WHERE active_slot=1').fetchone():
            raise CredentialBusy('凭据操作仍在进行，未更换存储。')
        policy=load(path.parent/'connection-policy.json')
        policy.update(schema_version='1',token_provider='keychain',auto_refresh_enabled='false',validated_contract_id='')
        save(path.parent/'connection-policy.json',policy)


def probe(path,synthetic=False):
    from .keychain_store import KeychainCredentialStore
    store=KeychainCredentialStore(path)
    if synthetic:
        reference=store.prefix+uuid.uuid4().hex;value=uuid.uuid4().hex
        try:
            store.backend().put(reference,value)
            if store.backend().get(reference)!=value:raise ApiError('钥匙串合成核对失败。')
        finally:store.backend().delete(reference)
    elif not store.read_refresh(load(path)):raise ApiError('当前会话没有钥匙串刷新凭据。')
    return dict(keychain_readable=True,synthetic=synthetic,checked_at=int(time.time()*1000))


def validate(path,deadline=600):
    session=load(path);store=credential_store(path)
    if not store.allow_refresh or not store.read_refresh(session):raise ApiError('先完成钥匙串短信登录。')
    if load(path.parent/'connection-policy.json').get('auto_refresh_enabled')=='true':
        raise ApiError('首次验证要求自动刷新保持关闭。')
    evidence=path.parent/'connection-validation.json'
    previous=load(evidence)
    if previous:
        if previous.get('refresh_result')=='refreshed' and previous.get('verified_scope')==session_scope(session):
            return verify_status(path,deadline)
        raise ApiError('已有一次验证意图，禁止重复刷新；请先核对已保存的验证状态。')
    baseline=refresh_fingerprint(session);now=int(time.time()*1000)
    save(evidence,dict(schema_version='1',refresh_result='dispatch_planned',checked_at=str(now),
                       target_status_verified='false',auto_refresh_enabled='false'))
    driver=RefreshDriver(path,policy=RefreshPolicy(enabled=True),store=store)
    # Eligibility evidence here is explicit human authorization, not fabricated
    # outage telemetry. This synthetic threshold is never written to incidents.
    result=driver.attempt(session,dict(attempts=3,opened_at=now-180000),now)
    receipt=dict(schema_version='1',refresh_result=result.kind,checked_at=str(now),
                 target_status_verified='false',auto_refresh_enabled='false')
    save(evidence,receipt)
    if result.kind!='refreshed':raise ApiError('单次刷新未完成：%s。自动刷新仍关闭，未重放请求。'%result.kind)
    active=load(path);receipt['new_refresh_token']=str(refresh_fingerprint(active)!=baseline).lower()
    receipt['verified_scope']=session_scope(active)
    receipt['refresh_completed_at']=str(int(time.time()*1000));save(evidence,receipt)
    return verify_status(path,deadline)


def verify_status(path,deadline=600):
    """Resume only protected reads; this function cannot issue refresh."""
    evidence=path.parent/'connection-validation.json';receipt=load(evidence)
    active=load(path)
    if receipt.get('refresh_result')!='refreshed' or receipt.get('verified_scope')!=session_scope(active):
        raise ApiError('缺少与当前会话一致的刷新提交证据；未重发刷新。')
    client=Client(active,query_policy=QueryPolicy(path.parent/'queries.sqlite3'))
    stop=time.monotonic()+deadline
    def protected(call):
        while True:
            if session_scope(load(path))!=session_scope(active):raise ApiError('验证期间会话已变化，未使用旧结果。')
            try:return call()
            except RequestDeferred as exc:
                if time.monotonic()+(exc.retry_after or 1)>stop:raise ApiError('查询保护仍在生效；刷新已保存，勿重复刷新。') from None
                time.sleep(exc.retry_after or 1)
    from .cli import find_vins
    binding=load(path.parent/'monitor-binding.json').get('vehicle_key')
    choices=[vin for vin in find_vins(protected(client.vehicles)) if hashlib.sha256(vin.encode()).hexdigest()==binding]
    if not binding or len(choices)!=1:raise ApiError('绑定车辆核对失败；未宣布恢复。')
    while True:
        raw=protected(lambda:client.status(choices[0]))
        outcome=client.query_outcome
        if not outcome.cache_hit:break
        wait=max(1,int((client.next_query_at or time.time()+1)-time.time())+1)
        if time.monotonic()+wait>stop:raise ApiError('仍命中缓存，尚未确认接口恢复；勿重复刷新。')
        time.sleep(wait)
    if not (outcome.actual_request and not outcome.cache_hit and outcome.schema_valid and outcome.success_code in ('1000','000000')):
        raise ApiError('未取得目标车辆的实际有效请求；勿重复刷新。')
    if session_scope(load(path))!=session_scope(active):raise ApiError('会话已更新，本次验证不授予启用资格。')
    if receipt.get('reuse_authorization') and receipt.get('new_refresh_token')!='true':
        CredentialCoordinator(path).accept_reuse(receipt['reuse_authorization'],active,outcome)
        receipt['reuse_verified']='true'
    receipt.update(target_status_verified='true',interface_recovered_at=str(int(time.time()*1000)),
                   validated_contract_id=uuid.uuid4().hex)
    # Vehicle timestamp is deliberately separate from interface recovery.
    from .vehicle_state import decode
    state=decode(raw,(),()).get('time')
    receipt['vehicle_state_time']=str(int(state)) if state is not None else ''
    save(evidence,receipt)
    policy=load(path.parent/'connection-policy.json')
    policy.update(validated_contract_id=receipt['validated_contract_id'],auto_refresh_enabled='false')
    save(path.parent/'connection-policy.json',policy)
    return {k:v for k,v in receipt.items() if k not in ('verified_scope','validated_contract_id')}


def validate_reuse(path,deadline=600):
    """One separately authorized real trial; never automatic or retried."""
    evidence=path.parent/'connection-reuse-validation.json'
    if load(evidence):raise ApiError('已有受控试验意图；禁止重复试验请求。')
    session=load(path);previous=load(path.parent/'connection-validation.json')
    if (previous.get('target_status_verified')!='true' or previous.get('verified_scope')!=session_scope(session)
            or load(path.parent/'connection-policy.json').get('auto_refresh_enabled')=='true'):
        raise ApiError('受控试验要求首次实际验证通过且自动开关关闭。')
    save(evidence,dict(state='intent_saved',baseline=session_scope(session)))
    coordinator=CredentialCoordinator(path)
    proof=coordinator.authorize_reuse(session_scope(session))
    save(evidence,dict(state='authorized',authorization=proof,baseline=session_scope(session)))
    now=int(time.time()*1000)
    result=RefreshDriver(path,policy=RefreshPolicy(enabled=True)).attempt(
        session,dict(attempts=3,opened_at=now-180000),now,reuse_authorization=proof)
    receipt=dict(schema_version='1',refresh_result=result.kind,target_status_verified='false',
                 auto_refresh_enabled='false',checked_at=str(now),reuse_authorization=proof)
    save(evidence,dict(state=result.kind,authorization=proof,baseline=session_scope(session)))
    if result.kind!='refreshed':raise ApiError('受控试验未成功；禁重放保持，不再请求。')
    active=load(path)
    receipt.update(verified_scope=session_scope(active),new_refresh_token=str(refresh_fingerprint(active)!=refresh_fingerprint(session)).lower(),
                   refresh_completed_at=str(int(time.time()*1000)))
    save(path.parent/'connection-validation.json',receipt)
    return verify_status(path,deadline)


def enable(path):
    receipt=load(path.parent/'connection-validation.json')
    coordinator=CredentialCoordinator(path)
    active=load(path)
    if (receipt.get('target_status_verified')!='true'
            or not (receipt.get('new_refresh_token')=='true' or coordinator.reusable(active))
            or receipt.get('verified_scope')!=session_scope(load(path))):
        raise ApiError('真实验证或新刷新凭据条件未满足，未启用。')
    probe(path)
    with coordinator.locked() as db:
        if db.execute('SELECT 1 FROM credential_operations WHERE active_slot=1').fetchone():raise CredentialBusy('凭据交换正在进行。')
        if session_scope(load(path))!=receipt['verified_scope']:raise CredentialBusy('启用前会话已变化。')
        policy=load(path.parent/'connection-policy.json')
        if policy.get('validated_contract_id')!=receipt.get('validated_contract_id'):raise ApiError('验证记录已变化。')
        policy['auto_refresh_enabled']='true';save(path.parent/'connection-policy.json',policy)
    return dict(auto_refresh_enabled=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',required=True,type=Path)
    parser.add_argument('--evidence',type=Path,help='Only non-secret probe result is written')
    parser.add_argument('action',choices=('login','probe','synthetic-probe','validate','validate-reuse','enable'))
    args=parser.parse_args()
    try:
        if args.action=='login':
            if not sys.stdin.isatty():raise ApiError('请在本机交互终端输入，勿将验证码发到聊天。')
            configure(args.session)
            from .cli import main as login
            result=login(['login'],session_path=args.session)
            if result:return result
            value=probe(args.session)
        elif args.action=='validate':value=validate(args.session)
        elif args.action=='validate-reuse':value=validate_reuse(args.session)
        elif args.action=='enable':value=enable(args.session)
        else:value=probe(args.session,args.action=='synthetic-probe')
        if args.evidence:save(args.evidence,{k:str(v) for k,v in value.items()})
        print(json.dumps(value,ensure_ascii=False));return 0
    except (ApiError,OSError):
        print('连接操作未完成。自动刷新未获新资格；请在本机核对连接状态。',file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
