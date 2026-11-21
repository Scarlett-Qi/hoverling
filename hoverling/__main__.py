"""Start the native desktop client for this platform."""
import sys


def main():
    if sys.platform == "linux":
        from .app import main as run_linux
        return run_linux()
    if sys.platform == "win32":
        try:
            from .windows.app import run
            return run()
        except Exception:
            # pythonw has no console for displaying a startup error.
            if sys.stderr is not None:
                raise
            import ctypes
            import traceback
            ctypes.windll.user32.MessageBoxW(None, traceback.format_exc(), "HoverLing 启动失败", 0x10)
            return 1
    raise SystemExit("HoverLing 支持 Linux X11 和 Windows。")


if __name__ == "__main__":
    raise SystemExit(main())
