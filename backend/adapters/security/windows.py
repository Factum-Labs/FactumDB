"""Current Windows identity plus Windows Hello verification by the native host.

Windows Hello stays in Tauri so the OS prompt can belong to the actual app
window. Python only receives a verification outcome and identifies its own SID.
"""

import ctypes as c
from ctypes import wintypes as w

from core.application.authentication import AuthenticationError


class WindowsDeviceSecurity:
    def __init__(self, *, verify_device=None):
        self.verify_device = verify_device
        self.adv = c.WinDLL("advapi32", use_last_error=True)
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.kernel.GetCurrentProcess.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.LocalFree.argtypes = [c.c_void_p]
        self.kernel.LocalFree.restype = c.c_void_p
        self.adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
        self.adv.OpenProcessToken.restype = w.BOOL
        self.adv.GetTokenInformation.argtypes = [
            w.HANDLE,
            c.c_int,
            c.c_void_p,
            w.DWORD,
            c.POINTER(w.DWORD),
        ]
        self.adv.GetTokenInformation.restype = w.BOOL
        self.adv.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(c.c_void_p)]
        self.adv.ConvertSidToStringSidW.restype = w.BOOL

    def _sid(self, token):
        size = w.DWORD()
        self.adv.GetTokenInformation(token, 1, None, 0, c.byref(size))
        if not size.value:
            raise AuthenticationError("Cannot identify the Windows device account")
        buffer = c.create_string_buffer(size.value)
        if not self.adv.GetTokenInformation(token, 1, buffer, size, c.byref(size)):
            raise AuthenticationError("Cannot identify the Windows device account")
        sid = c.cast(buffer, c.POINTER(c.c_void_p))[0]
        text = c.c_void_p()
        if not self.adv.ConvertSidToStringSidW(sid, c.byref(text)):
            raise AuthenticationError("Cannot identify the Windows device account")
        try:
            return "windows:sid:" + c.wstring_at(text)
        finally:
            self.kernel.LocalFree(text)

    def identity(self):
        token = w.HANDLE()
        if not self.adv.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, c.byref(token)):
            raise AuthenticationError("Cannot access the Windows device account")
        try:
            return self._sid(token)
        finally:
            self.kernel.CloseHandle(token)

    def verify(self):
        if self.verify_device is None:
            raise AuthenticationError(
                "Windows Hello verification requires the FactumDB desktop app"
            )
        self.verify_device()
        return self.identity()
