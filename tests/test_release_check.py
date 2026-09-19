"""Release gates use synthetic profiles/artwork, never vehicle credentials."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.release_check import ReleaseCheckError, check_release


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root/'zeekr_control'
        self.static = self.package/'static'
        self.static.mkdir(parents=True)
        self.config = self.package/'vehicle_profiles.json'
        self.config.write_text(json.dumps({'single_vehicle': {'image':'/car.svg'}, 'vehicles':{}}))
        self.png = b'\x89PNG\r\n\x1a\nsynthetic-artwork'
        (self.static/'car-001.png').write_bytes(self.png)
        self.svg = '<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,%s"/></svg>' % base64.b64encode(self.png).decode()
        (self.static/'car.svg').write_text(self.svg)

    def test_configured_image_and_matching_wrapper_pass(self):
        self.assertEqual(check_release(self.root, require_image=True), {'configured_images':1, 'artwork_checked':True})

    def test_permission_error_is_a_release_failure_not_unconfigured_success(self):
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path == self.config: raise PermissionError('PRIVATE-CONFIG-CONTENTS')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            with self.assertRaisesRegex(ReleaseCheckError, '配置无法读取') as caught:
                check_release(self.root, require_image=True)
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_missing_or_invalid_config_and_required_image_fail(self):
        for value in ('{bad', '[]', '{"vehicles":[]}', '{"single_vehicle":{"image":"https://invalid/car.png"}}', '{"single_vehicle":{}}'):
            self.config.write_text(value)
            with self.subTest(value=value), self.assertRaises(ReleaseCheckError):
                check_release(self.root, require_image=True)
        self.config.unlink()
        with self.assertRaises(ReleaseCheckError): check_release(self.root, require_image=True)
        self.assertFalse(check_release(self.root)['artwork_checked'])

    def test_missing_unreadable_or_different_artwork_fails(self):
        png = self.static/'car-001.png'
        png.unlink()
        with self.assertRaises(ReleaseCheckError): check_release(self.root, require_image=True)
        png.write_bytes(self.png+b'changed')
        with self.assertRaises(ReleaseCheckError): check_release(self.root, require_image=True)
        png.write_bytes(self.png)
        with patch.object(Path, 'read_bytes', side_effect=PermissionError('PRIVATE')):
            with self.assertRaises(ReleaseCheckError): check_release(self.root, require_image=True)
        (self.static/'car.svg').write_text('<svg>broken')
        with self.assertRaises(ReleaseCheckError): check_release(self.root, require_image=True)

    def test_actual_execution_user_is_enforced(self):
        import os, pwd
        user = pwd.getpwuid(os.geteuid()).pw_name
        self.assertTrue(check_release(self.root, service_user=user)['artwork_checked'])
        with patch('zeekr_control.release_check.os.geteuid', return_value=os.geteuid()+1):
            with self.assertRaisesRegex(ReleaseCheckError, '服务用户'):
                check_release(self.root, service_user=user)

    def test_keyed_image_works_without_single_vehicle_default(self):
        self.config.write_text(json.dumps({'vehicles':{'synthetic-key':{'image':'/car.svg'}}}))
        self.assertTrue(check_release(self.root, require_image=True)['artwork_checked'])
