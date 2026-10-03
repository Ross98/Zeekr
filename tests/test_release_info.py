import json
from pathlib import Path
import tempfile
import unittest


class ReleaseInfoTests(unittest.TestCase):
    def test_missing_manifest_is_unknown_and_hash_mismatch_not_online(self):
        from zeekr_control.release_info import read_release, write_manifest, FEATURES
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            self.assertEqual(read_release(root)['status'],'unrecorded')
            for relative in FEATURES['home-attention']['files']:
                p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic')
            write_manifest(root,'a'*40,['home-attention'])
            result=read_release(root)
            self.assertEqual(result['base_version'],'a'*40)
            self.assertEqual(result['features'][0]['status'],'matched')
            (root/FEATURES['home-attention']['files'][0]).write_text('modified')
            self.assertEqual(read_release(root)['features'][0]['status'],'mismatch')

    def test_invalid_manifest_does_not_expose_paths_or_private_fields(self):
        from zeekr_control.release_info import read_release
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'release-manifest.json').write_text(json.dumps({'base_version':'SECRET','features':{'../../session.json':{'label':'PRIVATE'}}}))
            result=read_release(root)
            self.assertEqual(result['status'],'invalid')
            self.assertNotIn('SECRET',json.dumps(result));self.assertNotIn('PRIVATE',json.dumps(result))
