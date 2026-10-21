"""Open the configured dashboard. Never start a server or create an SSH tunnel."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
from urllib.parse import urlsplit
import urllib.request


def dashboard_url(home=None, environ=None):
    home=Path(home or Path.home());environ=os.environ if environ is None else environ
    url=environ.get('ZEEKR_DASHBOARD_URL','').strip()
    if not url:
        config=home/'.config/zeekr/dashboard-url'
        if config.is_file():url=config.read_text().strip()
    if not url:
        agent=home/'Library/LaunchAgents/local.zeekr.web.plist'
        if agent.is_file():
            data=plistlib.loads(agent.read_bytes())
            url=data.get('EnvironmentVariables',{}).get('ZEEKR_PUBLIC_ORIGIN','')
    value=urlsplit(url)
    if (not value.hostname or value.username or value.password or value.query or value.fragment or
            value.path not in ('','/') or value.scheme not in ('http','https') or
            (value.scheme=='http' and value.hostname not in ('127.0.0.1','localhost'))):
        raise ValueError('请配置 HTTPS 网页地址：ZEEKR_DASHBOARD_URL 或 ~/.config/zeekr/dashboard-url。')
    return url.rstrip('/')+'/'


def main():
    try:
        url=dashboard_url()
        # Bypass shell proxy variables for the health read; browser retains its own settings.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=8) as response:
            if response.status != 200:raise ValueError('网页未就绪。')
        subprocess.run(['open',url],check=True)
        print('网页已打开；远程访问需连接同一 Tailscale 网络。')
    except Exception as error:
        print('未能打开网页：'+str(error),file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':sys.exit(main())
