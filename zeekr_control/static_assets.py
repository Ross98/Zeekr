"""Content-addressed private code assets; HTML and APIs remain uncached."""
import hashlib
import json
from pathlib import Path
import re


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def versions(root):
    return {'/'+path.relative_to(root).as_posix():digest(path.read_bytes())[:16]
            for path in sorted(Path(root).rglob('*')) if path.suffix in ('.js','.css')}


def manifest(root):
    paths = {path:path+'?v='+value for path,value in versions(root).items()}
    return ('window.ZeekrAssets=Object.freeze({url:function(path){return '+
            json.dumps(paths, separators=(',',':'))+'[path]||path;}});').encode()


def html(root, name):
    text = (Path(root)/name).read_text()
    values = versions(root)
    def replace(match):
        path = match[2]
        return match[1]+'="'+path+'?v='+values[path]+'"' if path in values else match[0]
    return re.sub(r'(src|href)="(/[^"?]+\.(?:js|css))"',replace,text).encode()
