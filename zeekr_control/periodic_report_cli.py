"""Manual preview/send entry point. No polling, cloud reads or automatic schedule."""
import argparse
import os
from pathlib import Path

from .storage import DEFAULT_PATH
from .periodic_report import ReportImage, PeriodicDelivery, demo_report


def main():
    parser=argparse.ArgumentParser(description='生成企业微信用车报表；默认只预览，不发送。')
    parser.add_argument('--period',required=True,choices=['day','week','month'])
    parser.add_argument('--date',help='报告期内日期 YYYY-MM-DD；正式报表须已结束')
    parser.add_argument('--theme',default='light',choices=['light','dark'])
    parser.add_argument('--session',type=Path,default=DEFAULT_PATH)
    parser.add_argument('--output',type=Path,help='新建预览PNG；父目录须私有')
    parser.add_argument('--demo',action='store_true',help='使用明确标记的演示数据')
    parser.add_argument('--send',action='store_true',help='明确发送真实报告，使用现有企业微信配置')
    args=parser.parse_args()
    if args.demo and args.send:parser.error('演示报告不可发送。')
    if not args.output and not args.send:parser.error('请指定--output预览文件。')
    if args.output:
        if args.output.exists() or args.output.is_symlink():parser.error('输出文件须不存在。')
        args.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        info=args.output.parent.stat()
        if args.output.parent.is_symlink() or info.st_uid!=os.getuid() or info.st_mode & 0o077:
            parser.error('输出父目录须为当前用户所有，权限700。')
    if args.demo:
        report=demo_report(args.period)
    else:
        if not args.date:parser.error('真实报告须指定--date。')
        from .web import App
        from .snapshots import session_scope
        from .personal_store import account_scope
        from .periodic_summary import PeriodicSummary
        app=App(args.session)
        try:
            with app.lock:
                session=app._read_session();app._restore_snapshot(session)
                if not session.get('accessToken') or not app.vehicle_key:
                    parser.error('当前账号无已确认车辆缓存。')
                scope=session_scope(session);owner=account_scope(session);vehicle=app.vehicle_key
                report=PeriodicSummary(app.database_path,app.archive_reader,app.personal_store).query(
                    scope,vehicle,owner,args.period,args.date,vehicle_time=(app.model or {}).get('updated_time'))
        finally:app.close()
    if args.output:
        image=ReportImage().render(report,args.theme)
        fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(image)
        print('报表预览已保存。')
    if args.send:
        from .notifications import WeComSender
        sender=WeComSender(args.session.parent/'wecom-webhook.json')
        result=PeriodicDelivery(args.session.parent/'periodic-reports.sqlite3').deliver(owner,vehicle,report,sender,args.theme)
        print('文字状态：%s；图片状态：%s。'%(result['text'],result['image']))


if __name__=='__main__':main()
