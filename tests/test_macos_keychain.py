"""Native bridge errors without touching real keychain items or lock settings."""
import os
import pwd
import sys
import unittest
from unittest.mock import patch
from zeekr_control.errors import ApiError
from zeekr_control.macos_keychain import MacKeychain


class MacKeychainTests(unittest.TestCase):
    def test_errors_expose_only_status_and_never_request_plaintext_fallback(self):
        for code in (-25308,-25300,-25293):
            with self.assertRaisesRegex(ApiError,str(code)):MacKeychain.check(code)

    @unittest.skipUnless(sys.platform=='darwin','Native framework unavailable')
    def test_uid_home_is_used_even_when_launchagent_home_differs(self):
        native=MacKeychain()
        expected=os.fsencode(pwd.getpwuid(os.getuid()).pw_dir+'/Library/Keychains/login.keychain-db')
        with patch.dict(os.environ,HOME='/synthetic/service-state'),patch.object(native.sec,'SecKeychainOpen',return_value=-25308) as opened,patch.object(native.cf,'CFRelease',wraps=native.cf.CFRelease) as released:
            with self.assertRaises(ApiError):
                with native.query('synthetic-account'):pass
        self.assertEqual(opened.call_args[0][0],expected)
        self.assertEqual(released.call_count,2)
