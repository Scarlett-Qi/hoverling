"""Optional launcher that records Python stacks if the GUI stops servicing timers."""
from datetime import datetime
import faulthandler
import os
from pathlib import Path
import threading


def main():
    folder = Path(os.environ["LOCALAPPDATA"]) / "HoverLing"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"hang-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.log"
    print(f"HoverLing diagnostic log: {path}", flush=True)
    with path.open("w", encoding="utf-8", buffering=1) as log:
        print(f"Started {datetime.now().isoformat(timespec='seconds')}; "
              f"UI thread 0x{threading.get_ident():x}", file=log)

        def heartbeat(event=None):
            faulthandler.dump_traceback_later(6, file=log)

        heartbeat()
        try:
            import wx
            from .app import Main
            app = wx.App(False)
            frame = Main()
            app.SetTopWindow(frame)
            timer = wx.Timer(app)
            app.Bind(wx.EVT_TIMER, heartbeat, timer)
            timer.Start(1000)
            frame.Show()
            app.MainLoop()
            timer.Stop()
        finally:
            faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
