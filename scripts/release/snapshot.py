"""Read-only public code snapshot. Never export runtime profiles or business data."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

# Source is concatenated after workflow.py; its main guard is disabled by caller.
base = Path('/opt/zeekr-control')
active = (base/'current').resolve()
manifest = {}
for name in inputs(active):
    path = active/name
    manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
release = json.loads((active/'release-manifest.json').read_text())
manifest['release-manifest.json'] = hashlib.sha256((active/'release-manifest.json').read_bytes()).hexdigest()
record = {'active': str(active), 'manifest': manifest, 'features': list(release['features'])}
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz') as archive:
    raw = json.dumps(record).encode()
    entry = tarfile.TarInfo('baseline.json')
    entry.size = len(raw)
    archive.addfile(entry, io.BytesIO(raw))
    for name in manifest:
        archive.add(active/name, arcname='staged/'+name, recursive=False)
