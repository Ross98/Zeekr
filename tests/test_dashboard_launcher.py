import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('open_dashboard',Path(__file__).parents[1]/'scripts/open-dashboard.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)


class DashboardLauncherTests(unittest.TestCase):
    def test_mini_reads_launch_agent_and_other_mac_uses_external_config(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);agent=home/'Library/LaunchAgents/local.zeekr.web.plist'
            agent.parent.mkdir(parents=True);agent.write_bytes(plistlib.dumps({
                'EnvironmentVariables':{'ZEEKR_PUBLIC_ORIGIN':'https://synthetic.ts.net'}}))
            self.assertEqual(launcher.dashboard_url(home,{}),'https://synthetic.ts.net/')
            config=home/'.config/zeekr/dashboard-url';config.parent.mkdir(parents=True)
            config.write_text('https://configured.ts.net\n')
            self.assertEqual(launcher.dashboard_url(home,{}),'https://configured.ts.net/')
            self.assertEqual(launcher.dashboard_url(home,{'ZEEKR_DASHBOARD_URL':'http://127.0.0.1:18765'}),
                             'http://127.0.0.1:18765/')

    def test_remote_http_credentials_queries_and_missing_config_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for url in ('','http://remote.test','https://user:pass@example.test',
                        'https://example.test?token=secret','https://example.test/#fragment',
                        'file:///etc/passwd','https://example.test/private'):
                with self.subTest(url=url),self.assertRaises(ValueError):
                    launcher.dashboard_url(folder,{'ZEEKR_DASHBOARD_URL':url})
