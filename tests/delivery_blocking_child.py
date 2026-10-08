"""Offline subprocess fixture: a sender waits on a local socket, never the Internet."""
from pathlib import Path
import socket
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from zeekr_control.delivery_runtime import DeliveryWorker


def main():
    channel=socket.socket(fileno=int(sys.argv[2]))
    def blocked_sender(*_):
        channel.sendall(b'S')
        channel.recv(1)
    worker=DeliveryWorker(Path(sys.argv[1])/'session.json',sender=blocked_sender,alert_sender=blocked_sender)
    worker.storage.tick=lambda *args,**kwargs:None
    worker.tick(now=int(sys.argv[3]))
    channel.close()


if __name__=='__main__':main()
