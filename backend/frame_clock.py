"""配信の期限待ち。Windowsでは高分解能の待機タイマーを使う。"""
import sys
import time

class FrameClock:
    def __init__(self):
        self.handle = None
        if sys.platform == 'win32':
            import ctypes
            self.ctypes = ctypes
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.CreateWaitableTimerExW.restype = ctypes.c_void_p
            self.kernel.SetWaitableTimer.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong), ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
            self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            self.handle = self.kernel.CreateWaitableTimerExW(None, None, 2, 0x1F0003)

    def wait(self, deadline):
        delay = deadline-time.perf_counter()
        if delay <= 0:
            return
        if self.handle:
            due = self.ctypes.c_longlong(-max(1,int(delay*10_000_000)))
            if self.kernel.SetWaitableTimer(self.handle, self.ctypes.byref(due), 0, None, None, False):
                self.kernel.WaitForSingleObject(self.handle, 0xFFFFFFFF)
                return
        time.sleep(delay)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
