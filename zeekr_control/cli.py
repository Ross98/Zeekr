"""Local interactive login and read-only commands."""
import argparse
import getpass
import hashlib
import json
import re
import sys

from .client import Client, ApiError
from .storage import DEFAULT_PATH, load, save, clear
from .summary import format_status


def redact(value, full=False):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = re.sub('[^a-z0-9]', '', key.lower())
            secret = any(part in normalized for part in ('token', 'password', 'secret', 'authorization', 'authcode', 'smscode'))
            private = any(part in normalized for part in (
                'phone', 'mobile', 'plate', 'latitude', 'longitude',
                'position', 'location', 'address', 'userid', 'clientid', 'owner',
            )) or normalized in (
                'vin', 'vehiclevin', 'lat', 'lon', 'lng', 'id', 'iccid', 'imsi', 'imei',
                'msisdn', 'temid', 'ihuid', 'loginuid', 'serialnumber', 'matcode',
                'engineno', 'deviceid',
            )
            result[key] = '[hidden]' if secret or (private and not full) else redact(item, full)
        return result
    if isinstance(value, list):
        return [redact(item, full) for item in value]
    return value


def find_vins(value):
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() == 'vin' and isinstance(item, str) and re.fullmatch('[A-HJ-NPR-Z0-9]{17}', item):
                found.add(item)
            elif isinstance(item, (dict, list)):
                found.update(find_vins(item))
    elif isinstance(value, list):
        for item in value:
            found.update(find_vins(item))
    return found


def parser():
    root = argparse.ArgumentParser(description='中国区老款 001 读取工具；显示缓存状态，不发送车控指令。')
    commands = root.add_subparsers(dest='command', required=True)
    login = commands.add_parser('login', help='终端交互登录，默认短信登录')
    login.add_argument('--token', action='store_true', help='隐藏输入已有 JWT，不发送短信')
    for command, help_text in [('vehicles', '读取账号车辆及分享车辆'), ('status', '读取缓存车辆状态')]:
        item = commands.add_parser(command, help=help_text)
        item.add_argument('--full', action='store_true', help='显示 VIN、位置等隐私字段，仅用于本机查看')
        if command == 'status':
            item.add_argument('--json', action='store_true', help='输出脱敏 JSON，便于核对字段')
            item.add_argument('--vehicle', type=int, help='选择车辆列表中的序号，从 1 开始')
    history = commands.add_parser('history-connect', help='隐藏输入已有 GW3 历史凭据，不重新登录车辆账号')
    history.add_argument('--vehicle', type=int, help='绑定车辆序号；单车可省略')
    commands.add_parser('logout', help='删除本机会话，不调用云端注销')
    web = commands.add_parser('web', help='启动本机 Web 界面，采集默认关闭')
    web.add_argument('--port', type=int, default=8765, help='本机端口，默认 8765')
    monitor = commands.add_parser('monitor', help='后台监控行程和充电，向已配置的企业微信群发送通知')
    monitor.add_argument('--vehicle', type=int, help='首次绑定车辆序号；单车可省略')
    monitor.add_argument('--once', action='store_true', help='执行一次检查及待发通知后退出')
    monitor.add_argument('--charging-active-code', action='append', default=[], help='仅填写本车实测确认的充电中 chargeSts，可重复')
    monitor.add_argument('--charging-stopped-code', action='append', default=[], help='仅填写本车实测确认的停止 chargeSts，可重复')
    commands.add_parser('monitor-status', help='查看监控健康状态和最近通知，不请求车辆或发送消息')
    return root


def main(argv=None, session_path=DEFAULT_PATH):
    args = parser().parse_args(argv)
    try:
        if args.command == 'monitor':
            from .monitor_runtime import run
            return run(session_path, args.vehicle, args.once, args.charging_active_code, args.charging_stopped_code)
        if args.command == 'monitor-status':
            from .monitor_runtime import read_status
            from pathlib import Path
            print(json.dumps(read_status(Path(session_path).parent), ensure_ascii=False, indent=2))
            return 0
        if args.command == 'web':
            if not 1 <= args.port <= 65535:
                raise ApiError('端口必须为 1–65535。')
            from .web import serve
            return serve(args.port)
        if args.command == 'logout':
            clear(session_path)
            print('本机会话已删除。')
            return 0
        if args.command == 'history-connect':
            if not sys.stdin.isatty():
                raise ApiError('请在运行 Web 服务的机器上使用交互终端；不要通过聊天、参数或管道传递凭据。')
            from .history import validate_session
            existing = load(session_path)
            vehicles = Client(existing).vehicles()
            if not vehicles or args.vehicle is None and len(vehicles) != 1:
                raise ApiError('请先查看 vehicles，再用 history-connect --vehicle 序号选择车辆。')
            index = args.vehicle if args.vehicle is not None else 1
            if index < 1 or index > len(vehicles):
                raise ApiError('车辆序号超出范围。')
            vins = find_vins(vehicles[index - 1])
            if len(vins) != 1:
                raise ApiError('选中车辆没有唯一有效 VIN。')
            print('仅导入同一账号、该车辆已有的 GW3 历史会话；GW2 Token 或 JWT 不能替代。')
            print('凭据在本机隐藏输入并保存。此操作不发送短信、不换取新会话；导入不代表权限已验证。')
            incoming = dict(existing,
                historyAccessToken=getpass.getpass('GW3 accessToken / Authorization（输入隐藏）：').strip(),
                historyDeviceId=getpass.getpass('对应 X-DEVICE-ID（输入隐藏）：').strip(),
                historyVin=getpass.getpass('该车辆加密后的 X-VIN（输入隐藏）：').strip(),
                historyVehicleKey=hashlib.sha256(next(iter(vins)).encode()).hexdigest())
            validate_session(incoming)
            if load(session_path) != existing:
                raise ApiError('输入期间车辆会话已变化，未覆盖，请重新连接。')
            save(session_path, incoming)
            print('历史凭据已保存。回到云端历史点击查询，验证实际权限；无需重启 Web。')
            return 0
        if args.command == 'login':
            if not sys.stdin.isatty():
                raise ApiError('请在本机交互终端运行登录；不要通过聊天、命令参数或管道传递凭据。')
            # A fresh client prevents old tokens contaminating a new account login.
            client = Client()
            print('请使用已分享车辆的副账号。新登录可能使该账号的官方 App 下线。')
            if args.token:
                client.login_jwt(getpass.getpass('粘贴 JWT（输入隐藏）：').strip())
            else:
                phone = getpass.getpass('副账号手机号（输入隐藏，回车发送短信）：').strip()
                client.send_sms(phone)
                print('短信请求已被网关接受。')
                code = getpass.getpass('短信验证码（输入隐藏）：').strip()
                client.login_sms(phone, code)
            save(session_path, client.session)
            print('认证完成，会话已保存。请运行 python3 -m zeekr_control vehicles 验证车辆访问。')
            return 0
        client = Client(load(session_path))
        vehicles = client.vehicles()
        if args.command == 'vehicles':
            result = [{'number': index, 'vehicle': entry} for index, entry in enumerate(vehicles, 1)]
        else:
            if not vehicles:
                raise ApiError('账号下未返回车辆；请核对车辆分享是否已接受。')
            if args.vehicle is None and len(vehicles) != 1:
                raise ApiError('有多辆车；先查看 vehicles，再用 status --vehicle 序号。')
            index = args.vehicle if args.vehicle is not None else 1
            if index < 1 or index > len(vehicles):
                raise ApiError('车辆序号超出范围。')
            vins = find_vins(vehicles[index - 1])
            if len(vins) != 1:
                raise ApiError('选中车辆没有唯一有效 VIN；需要核对响应字段。')
            result = client.status(next(iter(vins)))
            if client.last_query_cached:
                print("来源：本机 60 秒共享缓存，本次未重新请求车辆状态。", file=sys.stderr)
            if not args.json:
                print(format_status(result))
                return 0
            print('来源：GW2 缓存状态；可能延迟，请核对服务端时间字段。', file=sys.stderr)
        print(json.dumps(redact(result, args.full), ensure_ascii=False, indent=2))
        return 0
    except ApiError as exc:
        print('错误：' + str(exc), file=sys.stderr)
        return 1
    except ValueError:
        print('错误：本地配置或监控参数无效，请检查配置及运行实例。', file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\n操作已取消。', file=sys.stderr)
        return 130
    except OSError:
        print('错误：本地会话文件无法读写。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
