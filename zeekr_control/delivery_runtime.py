"""One supervised delivery process. It reads cached evidence and never polls cars."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from .delivery_state import delivery_lock, DeliveryBusy, DeliveryCancelled
from .storage import DEFAULT_PATH, load, save
from .sampling import read_settings
from .snapshots import SnapshotStore, session_scope
from .personal_store import PersonalStore, account_scope
from .notifications import WeComSender, BarkSender, FallbackSender, compact_bark_times
from .monitor import Monitor
from .focused_trip_image import FocusedTripImage
from .geocoding import AmapGeocoder
from .custom_reminders import Reminders
from .tyre_notifications import TyreNotifications
from .storage_health import StorageHealth
from .system_notifications import AuthFailureAlert

_DEFAULT=object()


class DeliveryWorker:
    def __init__(self,session_path=DEFAULT_PATH,*,sender=_DEFAULT,alert_sender=_DEFAULT,stop=None):
        self.session_path=Path(session_path);self.root=self.session_path.parent
        self.stop=stop or threading.Event()
        self.sender=WeComSender(self.root/'wecom-webhook.json') if sender is _DEFAULT else sender
        self.alert_sender=BarkSender(self.root/'bark.json') if alert_sender is _DEFAULT else alert_sender
        self.monitor=Monitor(self.root/'tracks.sqlite3',address_resolver=AmapGeocoder(self.root/'amap-geocoding.json'),
                             map_renderer=FocusedTripImage(self.root/'road-networks'))
        self.reminders=Reminders(PersonalStore(self.root/'personal.sqlite3'))
        self.tyres=TyreNotifications(self.reminders.store)
        self.storage=StorageHealth(self.root,self.sender,self.alert_sender)
        self.auth_alert=AuthFailureAlert(self.root,self.alert_sender)
        self.status='running';self.error='';self.deadline=None

    def guard(self,scope=None,vehicle=None):
        if self.stop.is_set() or self.deadline is not None and time.monotonic()>=self.deadline or not read_settings(self.root)[0]:raise DeliveryCancelled()
        if scope is not None:
            if session_scope(load(self.session_path))!=scope or load(self.root/'monitor-binding.json').get('vehicle_key')!=vehicle:
                raise DeliveryCancelled()

    def tick(self,now=None,image_limit=1,budget_seconds=None):
        now=int(time.time()*1000) if now is None else now
        self.error=''
        self.deadline=time.monotonic()+budget_seconds if budget_seconds is not None else None
        with delivery_lock(self.root/'notifications.lock'):
            # Server storage alerts deliberately remain active when vehicle sampling is paused.
            if self.stop.is_set():return
            try:self.storage.tick(now/1000,can_send=lambda:not self.stop.is_set() and (self.deadline is None or time.monotonic()<self.deadline))
            except Exception:
                self.error='storage_health_unavailable'
                print('存储巡检或预警状态无法保存，请检查存储。',flush=True)
            if not read_settings(self.root)[0]:
                self.status='paused';return
            self.status='running'
            try:
                self.auth_alert.deliver(self.guard)
                session=load(self.session_path);scope=session_scope(session)
                vehicle=load(self.root/'monitor-binding.json').get('vehicle_key')
                if not vehicle:return
                owner=account_scope(session)
                guard=lambda:self.guard(scope,vehicle)
                guard()
                snapshot=SnapshotStore(self.root/'snapshots.sqlite3').read(scope,vehicle)
                if snapshot:
                    fallback=(FallbackSender(self.alert_sender,self.sender,compact_bark_times)
                              if self.alert_sender is not None else self.sender)
                    self.reminders.deliver(owner,vehicle,snapshot['raw'],now,fallback,guard)
                    self.tyres.deliver(owner,vehicle,now,self.alert_sender,self.sender,guard)
                self.monitor.deliver(self.sender,now,self.alert_sender,guard,image_limit,vehicle)
            except DeliveryCancelled:
                self.status='paused' if not read_settings(self.root)[0] else 'running'

    def heartbeat(self):
        save(self.root/'delivery-health.json',{'status':self.status,'heartbeat':str(int(time.time()*1000)),
            'error_code':self.error})


class DeliveryProcess:
    """Collector-lock owner supervises a child with a pipe tied to its lifetime."""
    def __init__(self,session_path):
        self.session_path=Path(session_path);self.process=None;self.control=None
        self.retry_at=0;self.failures=0;self.started_at=0

    def ensure_running(self):
        if self.process is not None and self.process.poll() is None:return
        now=time.monotonic()
        if self.process is not None:
            if self.control is not None:os.close(self.control);self.control=None
            if now-self.started_at>60:self.failures=0
            self.failures+=1;self.retry_at=now+min(60,2**min(self.failures,6));self.process=None
        if now<self.retry_at:return
        read_fd,write_fd=os.pipe()
        try:
            self.process=subprocess.Popen([sys.executable,'-m','zeekr_control.delivery_runtime',
                '--session',str(self.session_path),'--control-fd',str(read_fd)],
                pass_fds=(read_fd,),start_new_session=True)
        except Exception:
            os.close(write_fd);self.retry_at=now+5
            print('通知后台暂无法启动，采集继续。',flush=True)
            return
        finally:os.close(read_fd)
        self.control=write_fd;self.started_at=now

    def close(self):
        if self.control is not None:os.close(self.control);self.control=None
        if self.process is None:return
        try:self.process.wait(timeout=22)
        except subprocess.TimeoutExpired:
            # The group also contains a potentially running image subprocess.
            try:os.killpg(self.process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:os.killpg(self.process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                self.process.wait(timeout=2)
        self.process=None


def run(session_path,control_fd):
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    def parent_lifetime():
        try:
            while os.read(control_fd,1):pass
        finally:
            os.close(control_fd);stop.set()
    threading.Thread(target=parent_lifetime,daemon=True).start()
    root=Path(session_path).parent
    with delivery_lock(root/'notifications.lock'):
        worker=DeliveryWorker(session_path,stop=stop)
        def heartbeat():
            while not stop.is_set():
                try:worker.heartbeat()
                except Exception:print('通知后台心跳无法保存。',flush=True)
                stop.wait(5)
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
        try:
            while not stop.is_set():
                try:worker.tick()
                except Exception:
                    worker.status='degraded';worker.error='delivery_unavailable'
                stop.wait(1)
        finally:
            stop.set();thread.join(2);worker.status='stopped';worker.heartbeat()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',type=Path,default=DEFAULT_PATH)
    parser.add_argument('--control-fd',type=int,required=True)
    args=parser.parse_args()
    try:run(args.session,args.control_fd)
    except DeliveryBusy:return


if __name__=='__main__':main()
