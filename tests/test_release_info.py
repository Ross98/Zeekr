import json
import os
from pathlib import Path
import tempfile
import unittest


class ReleaseInfoTests(unittest.TestCase):
    def test_invalid_manifest_storage_is_bounded_and_never_followed(self):
        from zeekr_control.release_info import read_release
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'release-manifest.json'
            target=root/'target';target.write_text('PRIVATE')
            for kind in ('oversized','directory','symlink','invalid-utf8'):
                with self.subTest(kind=kind):
                    if kind=='directory':path.mkdir()
                    elif kind=='symlink':path.symlink_to(target)
                    else:path.write_bytes(b' '*65537 if kind=='oversized' else b'\xff')
                    self.assertEqual(read_release(root),dict(status='invalid',base_version=None,features=[]))
                    if kind=='directory':path.rmdir()
                    else:path.unlink()
            self.assertEqual(target.read_text(),'PRIVATE')

    def test_deep_manifest_is_invalid_instead_of_crashing_state(self):
        from zeekr_control.release_info import read_release
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'release-manifest.json').write_text('['*1500+'0'+']'*1500)
            self.assertEqual(read_release(root),dict(status='invalid',base_version=None,features=[]))

    @unittest.skipUnless(hasattr(os,'mkfifo'),'requires FIFO support')
    def test_manifest_pipe_is_rejected_without_waiting_for_writer(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as temp:
            os.mkfifo(Path(temp)/'release-manifest.json',0o600)
            code=('import sys;from zeekr_control.release_info import read_release;'
                  'assert read_release(sys.argv[1])["status"]=="invalid"')
            result=subprocess.run([sys.executable,'-c',code,temp],capture_output=True,timeout=2)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_notification_features_verify_their_running_sources(self):
        from zeekr_control.release_info import read_release, write_manifest, FEATURES
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for feature in ('notification-brief','tyre-alerts'):
                for relative in FEATURES[feature]['files']:
                    path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('synthetic')
            write_manifest(root,'a'*40,['notification-brief','tyre-alerts'])
            self.assertTrue(all(f['status']=='matched' for f in read_release(root)['features']))
            (root/'zeekr_control/tyre_notifications.py').write_text('changed')
            self.assertEqual(read_release(root)['features'][1]['status'],'mismatch')

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

    def test_charging_readability_verifies_theme_and_chart_files(self):
        from zeekr_control.release_info import read_release, write_manifest, FEATURES
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for relative in FEATURES['charging-readability']['files']:
                p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic')
            write_manifest(root,'a'*40,['charging-readability'])
            self.assertEqual(read_release(root)['features'][0]['status'],'matched')
            (root/'zeekr_control/static/theme.css').write_text('changed')
            self.assertEqual(read_release(root)['features'][0]['status'],'mismatch')

    def test_overview_layout_checks_scoped_script_and_route(self):
        from zeekr_control.release_info import read_release, write_manifest, FEATURES
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for relative in FEATURES['overview-layout']['files']:
                p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic')
            write_manifest(root,'a'*40,['overview-layout'])
            self.assertEqual(read_release(root)['features'][0]['status'],'matched')
            (root/'zeekr_control/static/overview-dashboard.js').write_text('changed')
            self.assertEqual(read_release(root)['features'][0]['status'],'mismatch')
