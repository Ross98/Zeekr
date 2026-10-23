"""Narrow Security.framework generic-password API; no shell, sync or prompts."""
import ctypes as C
import sys
import os
import pwd
import threading
from contextlib import contextmanager,ExitStack
from .errors import ApiError

_lock=threading.Lock()
SERVICE='local.zeekr.refresh.v1'


class MacKeychain:
    def __init__(self):
        if sys.platform!='darwin':raise ApiError('macOS 钥匙串只在 macOS 可用。')
        self.cf=C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.sec=C.CDLL('/System/Library/Frameworks/Security.framework/Security')
        for name,restype,args in [
            ('CFStringCreateWithCString',C.c_void_p,[C.c_void_p,C.c_char_p,C.c_uint32]),
            ('CFDataCreate',C.c_void_p,[C.c_void_p,C.c_void_p,C.c_long]),
            ('CFArrayCreate',C.c_void_p,[C.c_void_p,C.POINTER(C.c_void_p),C.c_long,C.c_void_p]),
            ('CFDictionaryCreate',C.c_void_p,[C.c_void_p,C.POINTER(C.c_void_p),C.POINTER(C.c_void_p),C.c_long,C.c_void_p,C.c_void_p]),
            ('CFDataGetLength',C.c_long,[C.c_void_p]),('CFDataGetBytePtr',C.c_void_p,[C.c_void_p]),
            ('CFRelease',None,[C.c_void_p])]:
            fn=getattr(self.cf,name);fn.restype=restype;fn.argtypes=args
        for name,args in [('SecItemAdd',[C.c_void_p,C.c_void_p]),
                          ('SecKeychainOpen',[C.c_char_p,C.POINTER(C.c_void_p)]),
                          ('SecItemCopyMatching',[C.c_void_p,C.POINTER(C.c_void_p)]),
                          ('SecItemDelete',[C.c_void_p]),
                          ('SecKeychainGetUserInteractionAllowed',[C.POINTER(C.c_ubyte)]),
                          ('SecKeychainSetUserInteractionAllowed',[C.c_ubyte])]:
            fn=getattr(self.sec,name);fn.restype=C.c_int32;fn.argtypes=args

    def constant(self,name):return C.c_void_p.in_dll(self.sec,name).value

    @contextmanager
    def query(self,account,data=None,read=False):
        with ExitStack() as release:
            def string(value):
                ref=self.cf.CFStringCreateWithCString(None,value.encode(),0x08000100)
                if not ref:raise ApiError('钥匙串参数无法创建。')
                release.callback(self.cf.CFRelease,ref);return ref
            values={'kSecClass':self.constant('kSecClassGenericPassword'),
                    'kSecAttrService':string(SERVICE),'kSecAttrAccount':string(account)}
            # LaunchAgents deliberately override HOME. Search the current uid's
            # login keychain explicitly, never HOME's unrelated/default search list.
            keychain=C.c_void_p()
            path=os.path.join(pwd.getpwuid(os.getuid()).pw_dir,'Library/Keychains/login.keychain-db')
            self.check(self.sec.SecKeychainOpen(os.fsencode(path),C.byref(keychain)))
            release.callback(self.cf.CFRelease,keychain.value)
            if data is not None:values['kSecUseKeychain']=keychain.value
            else:
                callback=C.addressof(C.c_byte.in_dll(self.cf,'kCFTypeArrayCallBacks'))
                search=self.cf.CFArrayCreate(None,(C.c_void_p*1)(keychain.value),1,callback)
                if not search:raise ApiError('钥匙串搜索范围无法创建。')
                release.callback(self.cf.CFRelease,search);values['kSecMatchSearchList']=search
            if read:
                values['kSecReturnData']=C.c_void_p.in_dll(self.cf,'kCFBooleanTrue').value
                values['kSecMatchLimit']=self.constant('kSecMatchLimitOne')
            if data is not None:
                encoded=data.encode();ref=self.cf.CFDataCreate(None,encoded,len(encoded))
                if not ref:raise ApiError('钥匙串数据无法创建。')
                release.callback(self.cf.CFRelease,ref);values['kSecValueData']=ref
                # File-based user keychain, device-local and never synchronizable.
                values['kSecAttrSynchronizable']=C.c_void_p.in_dll(self.cf,'kCFBooleanFalse').value
            keys=(C.c_void_p*len(values))(*(self.constant(k) for k in values))
            entries=(C.c_void_p*len(values))(*values.values())
            key_cb=C.addressof(C.c_byte.in_dll(self.cf,'kCFTypeDictionaryKeyCallBacks'))
            value_cb=C.addressof(C.c_byte.in_dll(self.cf,'kCFTypeDictionaryValueCallBacks'))
            query=self.cf.CFDictionaryCreate(None,keys,entries,len(values),key_cb,value_cb)
            if not query:raise ApiError('钥匙串查询无法创建。')
            release.callback(self.cf.CFRelease,query)
            with _lock:
                previous=C.c_ubyte()
                if self.sec.SecKeychainGetUserInteractionAllowed(C.byref(previous)) or self.sec.SecKeychainSetUserInteractionAllowed(0):
                    raise ApiError('钥匙串非交互保护无法启用。')
                try:yield query
                finally:self.sec.SecKeychainSetUserInteractionAllowed(previous.value)

    @staticmethod
    def check(status):
        if status:raise ApiError('钥匙串不可用（OSStatus %d）；未回退明文。'%status)

    def get(self,account):
        result=C.c_void_p()
        with self.query(account,read=True) as query:
            self.check(self.sec.SecItemCopyMatching(query,C.byref(result)))
        try:
            length=self.cf.CFDataGetLength(result)
            if not 0<length<=65536:raise ValueError()
            value=C.string_at(self.cf.CFDataGetBytePtr(result),length).decode()
            return value
        except (ValueError,UnicodeError):raise ApiError('钥匙串项目格式无效。') from None
        finally:
            if result.value:self.cf.CFRelease(result)

    def put(self,account,value):
        with self.query(account,data=value) as query:status=self.sec.SecItemAdd(query,None)
        if status==-25299:
            if self.get(account)!=value:raise ApiError('钥匙串候选引用冲突。')
        else:self.check(status)

    def delete(self,account):
        with self.query(account) as query:status=self.sec.SecItemDelete(query)
        if status!=-25300:self.check(status)
