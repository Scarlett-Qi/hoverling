"""Observe primary-button transitions without consuming application input."""
import ctypes
from ctypes import wintypes

from .selection import external_process_window, user32


class MouseEvent(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


HookProc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HookProc, wintypes.HMODULE, wintypes.DWORD)
user32.SetWindowsHookExW.restype = wintypes.HANDLE
user32.CallNextHookEx.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = (wintypes.HANDLE,)
user32.WindowFromPoint.argtypes = (wintypes.POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetAncestor.restype = wintypes.HWND
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def window_at(point):
    hwnd = user32.WindowFromPoint(wintypes.POINT(*point))
    return external_process_window(user32.GetAncestor(hwnd, 2)) if hwnd else None  # GA_ROOT


class MouseButtons:
    def __init__(self, notify):
        self.notify = notify
        self.swapped = bool(user32.GetSystemMetrics(23))  # SM_SWAPBUTTON
        self.messages = (0x0204, 0x0205) if self.swapped else (0x0201, 0x0202)
        self.callback = HookProc(self.handle)
        self.hook = user32.SetWindowsHookExW(14, self.callback, kernel32.GetModuleHandleW(None), 0)
        self.down = False

    def handle(self, code, message, data):
        try:
            if code == 0 and message in self.messages:
                event = MouseEvent.from_address(data)
                self.notify(message == self.messages[0], (event.pt.x, event.pt.y), event.time)
        finally:
            result = user32.CallNextHookEx(None, code, message, data)
        return result

    def poll_fallback(self, point, timestamp):
        if not self.hook:
            down = bool(user32.GetAsyncKeyState(2 if self.swapped else 1) & 0x8000)
            if down != self.down:
                self.down = down
                self.notify(down, point, timestamp)

    def close(self):
        if self.hook:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
