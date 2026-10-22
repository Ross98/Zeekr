"""Native macOS smoke with temporary synthetic state; no installed services needed."""
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from zeekr_control.resource_monitor import host_cpu_ticks,host_cpu_delta,native,NativeSampler,probe_origin
from zeekr_control.storage_health import alert_capacity


@unittest.skipUnless(sys.platform=='darwin','Darwin native integration runs on macOS')
class MacOSNativeTests(unittest.TestCase):
    def test_actual_host_ticks_and_exported_pressure(self):
        before=host_cpu_ticks();time.sleep(.15);after=host_cpu_ticks()
        self.assertTrue(0<=host_cpu_delta(before,after)<=100)
        self.assertIn(int(native(['/usr/sbin/sysctl','-n','kern.memorystatus_vm_pressure_level']).strip()),(1,2,4))

    def test_actual_foundation_capacity(self):
        with tempfile.TemporaryDirectory() as folder:
            usage=shutil.disk_usage(folder)
            sample=alert_capacity(Path(folder),usage)
            self.assertEqual(sample['capacity_basis'],'macos_important_usage')
            self.assertTrue(0<=sample['capacity_available_bytes']<=usage.total)
            self.assertTrue(0<=sample['capacity_used_percent']<=100)

    def test_native_process_counters_reap_child_cpu_without_dropping_window(self):
        # Parent waits for a short CPU worker and stays alive for the second ps.
        worker='import time; end=time.process_time()+.35\nwhile time.process_time()<end: pass'
        parent="import subprocess,sys; print('ready',flush=True); input(); subprocess.run([sys.executable,'-c',sys.argv[1]],check=True); print('done',flush=True); input()"
        with subprocess.Popen([sys.executable,'-c',parent,worker],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True) as child:
            try:
                self.assertTrue(select.select([child.stdout],[],[],5)[0]);self.assertEqual(child.stdout.readline().strip(),'ready')
                def command(argv):
                    if argv[0].endswith('launchctl'):return '\tstate = running\n\tpid = %d\n'%child.pid
                    return native(argv)
                sampler=NativeSampler(command,probe=lambda origin:True,origin_reader=lambda:'https://synthetic.invalid')
                sampler.measure();start=sampler.checked
                child.stdin.write('go\n');child.stdin.flush()
                self.assertTrue(select.select([child.stdout],[],[],5)[0]);self.assertEqual(child.stdout.readline().strip(),'done')
                sample=sampler.measure();elapsed=sampler.checked-start
                self.assertTrue(sample['app_cpu_complete'])
                self.assertGreater(sample['app_cpu_percent']*elapsed/100,.2,'native counters must include the waited child CPU')
            finally:child.kill();child.wait(timeout=5)

    def test_real_loopback_probe_keeps_auth_boundary(self):
        from zeekr_control.auth import WebAuth,password_record
        from zeekr_control.web import App,make_server
        with tempfile.TemporaryDirectory() as folder:
            app=App(Path(folder)/'session.json')
            server=make_server(app,0,auth=WebAuth(password_record('synthetic native test password')))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:self.assertTrue(probe_origin('http://127.0.0.1:'+str(server.server_port)))
            finally:server.shutdown();server.server_close();thread.join(timeout=5);app.close()
