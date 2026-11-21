"""Read the current selection using Windows UI Automation on a worker thread."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import queue
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short


def external_window():
    return external_process_window(user32.GetForegroundWindow())


def external_process_window(window):
    process = wintypes.DWORD()
    if window and user32.GetWindowThreadProcessId(window, ctypes.byref(process)) and process.value != os.getpid():
        return window
    return None


def selected_text(automation, module, pattern_errors):
    element = automation.GetFocusedElement()
    for _ in range(5):
        if not element or element.CurrentIsPassword:
            return None
        try:
            pattern = element.GetCurrentPattern(10014)  # UIA_TextPatternId
            if pattern:
                ranges = pattern.QueryInterface(module.IUIAutomationTextPattern).GetSelection()
                if ranges and ranges.Length > 1:
                    return None
                if ranges and ranges.Length == 1:
                    # UIA providers may count UTF-16 units. Any prefix truncated
                    # at 10,001 units is necessarily over 5,000 code points.
                    text = ranges.GetElement(0).GetText(10001)
                    if text and text.strip():
                        return text
        except pattern_errors:
            pass
        element = automation.ControlViewWalker.GetParentElement(element)
    return None


class SelectionReader:
    def __init__(self, deliver, unavailable):
        self.unavailable = unavailable
        self.deliver = deliver
        self.jobs = queue.Queue(maxsize=1)
        threading.Thread(target=self.run, daemon=True, name="UIAutomation").start()

    def submit(self, job):
        try:
            self.jobs.get_nowait()
        except queue.Empty:
            pass
        self.jobs.put_nowait(job)

    def run(self):
        # Importing comtypes initializes COM on this thread. Use the MTA
        # recommended for cross-process UI Automation clients.
        import sys
        sys.coinit_flags = 0
        try:
            from comtypes import COMError
            import comtypes.client as client
            client.gen_dir = None
            module = client.GetModule(str(Path(os.environ["SystemRoot"]) / "System32" / "UIAutomationCore.dll"))
            automation = client.CreateObject(module.CUIAutomation, interface=module.IUIAutomation)
        except Exception:
            self.unavailable()
            return
        while True:
            serial, window, point = self.jobs.get()
            if external_window() != window:
                continue
            try:
                text = selected_text(automation, module, (COMError, OSError, ValueError))
                if text and external_window() == window:
                    self.deliver(serial, window, point, text)
            except Exception:
                # Unsupported providers, closed windows and access-denied
                # controls are normal while switching between applications.
                continue
