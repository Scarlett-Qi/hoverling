from ctypes import wintypes
import os
from pathlib import Path
import threading
import time

import wx
import wx.adv
from .. import __version__
from ..theme import CARD_PADDING, CONTROL_RADIUS, WORD
from ..core import explicit_target
from ..formatting import render_markdown
from ..translate import TranslationError, Translator
from .gestures import SelectionGesture
from .mouse import MouseButtons, window_at
from .secrets import WindowsSettings
from .selection import SelectionReader, external_window, user32
from .settings import SettingsDialog, mode_label
from .style import CANVAS, MUTED, PAPER, Surface, action, label, reading_field, typeface, window_corners


CLIPBOARD_HOTKEY = 1
TOGGLE_HOTKEY = 2
TRANSLATION_WAIT_SECONDS = 60
# Win32 modifier values. MOD_NOREPEAT keeps a held key from toggling repeatedly.
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
user32.RegisterHotKey.argtypes = (wintypes.HWND, wintypes.INT, wintypes.UINT, wintypes.UINT)


def set_clipboard(text):
    if not text or not wx.TheClipboard.Open():
        return
    try:
        wx.TheClipboard.SetData(wx.TextDataObject(text))
        wx.TheClipboard.Flush()
    finally:
        wx.TheClipboard.Close()


class Preview(wx.Frame):
    MIN_HEIGHT = 200
    DEFAULT_HEIGHT = 320

    def __init__(self, owner):
        super().__init__(owner, title="划词翻译", style=wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.FRAME_TOOL_WINDOW | wx.RESIZE_BORDER)
        window_corners(self, small=True)
        self.owner = owner
        self.source = ""
        self.deadline = None
        self.inside = False
        panel = Surface(self)
        self.SetBackgroundColour(CANVAS)
        d = panel.FromDIP
        layout = wx.BoxSizer(wx.VERTICAL)
        head = wx.BoxSizer(wx.HORIZONTAL)
        self.heading = wx.StaticText(panel, style=wx.ST_ELLIPSIZE_END | wx.ST_NO_AUTORESIZE)
        typeface(self.heading, 14, bold=True)
        self.heading.SetForegroundColour(WORD)
        self.heading.SetMinSize((1, self.heading.GetTextExtent("所选原文").height))
        head.Add(self.heading, 1, wx.ALIGN_CENTER_VERTICAL)
        head.AddSpacer(d(10))
        close = action(panel, "×", self.Hide)
        close.SetName("关闭浮窗")
        close.SetToolTip("关闭浮窗")
        head.Add(close)
        layout.Add(head, 0, wx.EXPAND)
        layout.AddSpacer(d(10))
        self.content = reading_field(panel, "划词内容")
        layout.Add(self.content, 1, wx.EXPAND)
        layout.AddSpacer(d(10))
        self.note = wx.StaticText(panel, style=wx.ST_ELLIPSIZE_END | wx.ST_NO_AUTORESIZE)
        typeface(self.note, 9)
        self.note.SetForegroundColour(MUTED)
        self.note.SetMinSize((1, self.note.GetTextExtent("翻译来源").height))
        layout.Add(self.note, 0, wx.EXPAND)
        layout.AddSpacer(d(10))
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.translate = action(panel, "翻译选中文字", lambda: owner.translate(self.source))
        self.copy = action(panel, "复制选中文字", self.copy_displayed)
        row.Add(self.translate, 1)
        row.AddSpacer(d(8))
        row.Add(self.copy, 1)
        layout.Add(row, 0, wx.EXPAND)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(layout, 1, wx.EXPAND | wx.ALL, d(CARD_PADDING))
        panel.SetSizer(outer)
        layout_file = owner.settings.path.with_name("window.ini")
        self.geometry = wx.FileConfig(localFilename=str(layout_file), style=wx.CONFIG_USE_LOCAL_FILE)
        height = self.geometry.ReadInt("popup_height", self.DEFAULT_HEIGHT)
        self.preferred_height = height if self.MIN_HEIGHT <= height <= 32767 else self.DEFAULT_HEIGHT
        self.height_before_drag = None
        self.Bind(wx.EVT_MOVE_START, self.begin_resize)
        self.Bind(wx.EVT_MOVE_END, self.end_resize)
        self.Bind(wx.EVT_CLOSE, lambda event: self.Hide())

    def begin_resize(self, event):
        self.height_before_drag = self.GetClientSize().height
        event.Skip()

    def end_resize(self, event):
        before = self.height_before_drag
        self.height_before_drag = None
        self.inside = True
        self.deadline = None
        after = self.GetClientSize().height
        if before is not None and after != before:
            self.preferred_height = max(self.MIN_HEIGHT, self.ToDIP(after))
            try:
                self.owner.settings.path.parent.mkdir(parents=True, exist_ok=True)
                if not self.geometry.WriteInt("popup_height", self.preferred_height) or not self.geometry.Flush():
                    raise OSError("Unable to save window geometry")
            except OSError:
                self.owner.SetStatusText("无法保存浮窗高度，请检查配置目录的写入权限")
        event.Skip()

    def copy_displayed(self):
        set_clipboard(self.content.GetValue())

    def set_note(self, text):
        self.note.SetLabelText(text)
        self.note.SetToolTip(text)

    def present(self, text, point):
        self.source = text
        self.heading.SetLabelText(" ".join(text.split()))
        self.heading.SetToolTip(text)
        self.content.ChangeValue(text)
        self.set_note("尚未联网 · 点翻译后只使用选中文字")
        self.translate.SetLabel("翻译选中文字")
        self.translate.Enable()
        self.copy.SetLabel("复制选中文字")
        self.copy.Enable()
        screen = wx.Display.GetFromPoint(point)
        area = wx.Display(max(0, screen)).GetClientArea()
        desired = self.ClientToWindowSize(self.FromDIP((390, self.preferred_height)))
        minimum = self.ClientToWindowSize(self.FromDIP((390, self.MIN_HEIGHT)))
        width = min(desired.width, area.width)
        height = min(desired.height, area.height)
        self.SetSizeHints(width, min(minimum.height, area.height), width, area.height)
        gap = self.FromDIP(10)
        x = min(max(area.x, point.x + gap), max(area.x, area.x + area.width - width))
        y = point.y + gap
        if y + height > area.y + area.height:
            y = max(area.y, point.y - height - gap)
        self.SetSize(x, y, width, height)
        self.inside = False
        self.deadline = time.monotonic() + 1.5
        self.ShowWithoutActivating()

    def track(self, point):
        if not self.IsShown() or self.height_before_drag is not None:
            return
        now = time.monotonic()
        if self.GetScreenRect().Contains(point):
            self.inside, self.deadline = True, None
        elif self.inside:
            self.inside, self.deadline = False, now + 0.5
        elif self.deadline is not None and now >= self.deadline:
            self.Hide()


class Tray(wx.adv.TaskBarIcon):
    def __init__(self, owner, icon):
        super().__init__()
        self.owner = owner
        self.SetIcon(icon, "HoverLing 指译")
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_UP, self.left_menu)
        # TaskBarIcon opens CreatePopupMenu on the native right-click event.

    def CreatePopupMenu(self):
        menu = wx.Menu()
        for label, action in [("打开主界面", self.owner.open), ("设置", self.owner.configure), ("退出", self.owner.quit)]:
            if label == "退出":
                menu.AppendSeparator()
            item = menu.Append(wx.ID_ANY, label)
            menu.Bind(wx.EVT_MENU, lambda event, fn=action: wx.CallAfter(fn), item)
        return menu

    def left_menu(self, event):
        menu = self.CreatePopupMenu()
        try:
            self.PopupMenu(menu)
        finally:
            menu.Destroy()


class Main(wx.Frame):
    def __init__(self):
        super().__init__(None, title="HoverLing 指译")
        window_corners(self)
        self.SetClientSize(self.FromDIP((486, 584)))
        self.SetMinSize(self.FromDIP((428, 530)))
        self.settings = WindowsSettings(Path(os.environ["LOCALAPPDATA"]) / "HoverLing" / "settings.json")
        self.translator = Translator()
        self.closed = False
        self.select_id = self.request_id = 0
        self.busy = None
        self.gesture = SelectionGesture()
        panel = wx.Panel(self)
        panel.SetBackgroundColour(CANVAS)
        d = panel.FromDIP
        layout = wx.BoxSizer(wx.VERTICAL)
        head = wx.BoxSizer(wx.HORIZONTAL)
        head.Add(label(panel, "指译 HoverLing", 17, bold=True), 0, wx.ALIGN_CENTER_VERTICAL)
        head.Add(label(panel, f"v{__version__}", 9, MUTED), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, d(8))
        layout.Add(head, 0, wx.EXPAND)
        layout.AddSpacer(d(8))
        layout.Add(label(panel, "自己划选文字，只翻译你选中的内容。", 9, MUTED))
        layout.AddSpacer(d(14))

        card = Surface(panel)
        controls = wx.BoxSizer(wx.VERTICAL)
        self.service = label(card, "", 11)
        controls.Add(self.service, 0, wx.EXPAND)
        controls.AddSpacer(d(10))
        self.toggle = action(card, "暂停划词翻译", self.toggle_selection, primary=True)
        controls.Add(self.toggle, 0, wx.EXPAND)
        controls.AddSpacer(d(10))
        self.clipboard_button = action(card, "读取剪贴板", self.clipboard)
        controls.Add(self.clipboard_button, 0, wx.EXPAND)
        card_box = wx.BoxSizer(wx.VERTICAL)
        card_box.Add(controls, 1, wx.EXPAND | wx.ALL, d(CARD_PADDING))
        card.SetSizer(card_box)
        self.update_controls()
        layout.Add(card, 0, wx.EXPAND)
        layout.AddSpacer(d(12))
        layout.Add(action(panel, "取词与 AI 设置", self.configure), 0, wx.EXPAND)
        layout.AddSpacer(d(14))
        layout.Add(label(panel, "也可以手动输入或粘贴文字（英语、日语等）", 9, MUTED))
        layout.AddSpacer(d(6))

        entry_row = wx.BoxSizer(wx.HORIZONTAL)
        entry = Surface(panel, radius=CONTROL_RADIUS)
        self.source = reading_field(entry, "原文", editable=True)
        self.source.SetHint("例如：It's a piece of cake. / いらっしゃいませ")
        entry.watch_input(self.source)
        inset = wx.BoxSizer(wx.VERTICAL)
        inset.Add(self.source, 1, wx.EXPAND | wx.ALL, d(7))
        entry.SetSizer(inset)
        entry.SetMinSize(d((-1, 50)))
        entry_row.Add(entry, 1, wx.EXPAND)
        entry_row.AddSpacer(d(8))
        self.go = action(panel, "翻译", lambda: self.translate(self.source.GetValue()))
        entry_row.Add(self.go, 0, wx.ALIGN_CENTER_VERTICAL)
        layout.Add(entry_row, 0, wx.EXPAND)
        layout.AddSpacer(d(12))
        output = wx.Panel(panel)
        output.SetBackgroundColour(PAPER)
        result_box = wx.BoxSizer(wx.VERTICAL)
        self.result = reading_field(output, "译文与释义")
        self.result.ChangeValue("先划选要翻译的文字，再点击浮窗中的“翻译选中文字”。")
        result_box.Add(self.result, 1, wx.EXPAND)
        self.copy = action(output, "复制结果", lambda: set_clipboard(self.result.GetValue()), quiet=True)
        result_box.Add(self.copy, 0, wx.ALIGN_RIGHT)
        self.copy.Hide()
        result_outer = wx.BoxSizer(wx.VERTICAL)
        result_outer.Add(result_box, 1, wx.EXPAND | wx.ALL, d(12))
        output.SetSizer(result_outer)
        layout.Add(output, 1, wx.EXPAND)
        shell = wx.BoxSizer(wx.VERTICAL)
        shell.Add(layout, 1, wx.ALL | wx.EXPAND, d(22))
        panel.SetSizer(shell)
        bar = self.CreateStatusBar(style=wx.STB_ELLIPSIZE_END | wx.STB_SHOW_TIPS)
        typeface(bar, 9)
        bar.SetBackgroundColour(CANVAS)
        bar.SetForegroundColour(MUTED)
        icon = wx.Icon(str(Path(__file__).with_name("HoverLing.ico")), wx.BITMAP_TYPE_ICO)
        self.SetIcon(icon)
        self.preview = Preview(self)
        self.tray = Tray(self, icon)
        self.reader = SelectionReader(self.deliver, self.selection_unavailable)
        self.hotkey = self.RegisterHotKey(CLIPBOARD_HOTKEY, wx.MOD_CONTROL | wx.MOD_ALT, ord("C"))
        self.toggle_hotkey = user32.RegisterHotKey(
            self.GetHandle(), TOGGLE_HOTKEY, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("Y")
        )
        toggle_hint = "Ctrl+Alt+Y 开关划词" if self.toggle_hotkey else "Ctrl+Alt+Y 不可用，请点击按钮开关划词"
        clipboard_hint = "Ctrl+Alt+C 预览剪贴板" if self.hotkey else "Ctrl+Alt+C 不可用，请点击按钮读取剪贴板"
        self.toggle.SetToolTip(toggle_hint)
        self.clipboard_button.SetToolTip(clipboard_hint)
        self.SetStatusText(toggle_hint + " · " + clipboard_hint)
        self.Bind(wx.EVT_HOTKEY, lambda event: self.clipboard(), id=CLIPBOARD_HOTKEY)
        self.Bind(wx.EVT_HOTKEY, lambda event: self.toggle_selection(), id=TOGGLE_HOTKEY)
        self.source.Bind(wx.EVT_TEXT, self.edit)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.poll, self.timer)
        self.mouse = MouseButtons(self.mouse_button)
        self.timer.Start(60 if self.mouse.hook else 16)
        self.Centre()

    def selection_unavailable(self):
        if not self.closed:
            wx.CallAfter(self.show_selection_hint)

    def show_selection_hint(self):
        if not self.closed:
            self.SetStatusText("系统选区接口不可用，可复制后读取剪贴板")

    def open(self):
        self.Show()
        self.Iconize(False)
        self.Raise()

    def update_controls(self):
        enabled = self.settings.values["trigger"] == "selection"
        status = "划词翻译已开启" if enabled else "划词翻译已暂停"
        self.service.SetLabel(status + " · " + mode_label(self.settings.values))
        self.toggle.SetLabel("暂停划词翻译" if enabled else "开启划词翻译")

    def toggle_selection(self):
        trigger = "alt" if self.settings.values["trigger"] == "selection" else "selection"
        try:
            self.settings.save({"trigger": trigger})
        except OSError as exc:
            wx.MessageBox(str(exc), "无法保存设置", parent=self)
            return
        self.select_id += 1
        self.gesture.reset()
        self.update_controls()

    def configure(self):
        self.preview.Hide()
        with SettingsDialog(self, self.settings) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.update_controls()
                self.service.GetParent().Layout()
                self.invalidate()
                self.select_id += 1
                self.gesture.reset()
                self.SetStatusText("设置已保存")

    def invalidate(self):
        self.request_id += 1
        self.busy = None
        self.copy.Hide()
        self.copy.GetParent().Layout()
        self.result.ChangeValue("")
        self.go.Enable()

    def edit(self, event):
        self.invalidate()
        self.select_id += 1
        self.preview.Hide()
        event.Skip()

    def poll(self, event):
        point = wx.GetMousePosition()
        self.preview.track(point)
        if self.busy is not None and time.monotonic() >= self.translation_deadline:
            self.finish(self.request_id, "等待翻译结果超时。可以重新翻译，或在设置中更换服务。", "翻译未完成")
        if not self.mouse.hook:
            self.mouse.poll_fallback(tuple(point), time.monotonic_ns() // 1_000_000)

    def mouse_button(self, down, point, timestamp):
        if self.closed or self.settings.values["trigger"] != "selection":
            return
        window = window_at(point)
        if down:
            self.select_id += 1
            self.gesture.down(window, point, timestamp)
        elif self.gesture.up(window, point, self.FromDIP(4), user32.GetDoubleClickTime(),
                             (user32.GetSystemMetrics(36), user32.GetSystemMetrics(37))):
            # Let the other application finish updating its selection first.
            wx.CallLater(80, self.read, self.select_id, window, wx.Point(*point))

    def read(self, serial, window, point):
        if not self.closed and serial == self.select_id and external_window() == window:
            self.reader.submit((serial, window, point))

    def deliver(self, serial, window, point, text):
        if not self.closed:
            wx.CallAfter(self.receive, serial, window, point, text)

    def receive(self, serial, window, point, text):
        if not self.closed and serial == self.select_id and external_window() == window:
            self.present(text, point)

    def present(self, text, point):
        if not text.strip() or len(text) > 5000:
            self.preview.Hide()
            self.SetStatusText("请选择 1 到 5000 个字符")
            return
        self.invalidate()
        self.source.ChangeValue(text.strip())
        self.preview.present(text.strip(), point)
        self.SetStatusText("已读取选区，点击翻译后查询")

    def clipboard(self):
        self.select_id += 1
        data = wx.TextDataObject()
        ok = False
        if wx.TheClipboard.Open():
            try:
                ok = wx.TheClipboard.GetData(data)
            finally:
                wx.TheClipboard.Close()
        if ok and data.GetText().strip() and len(data.GetText()) <= 5000:
            self.present(data.GetText(), wx.GetMousePosition())
        else:
            self.open()
            self.SetStatusText("请先复制 1 到 5000 个字符，再读取剪贴板")

    def translate(self, text):
        text = text.strip()
        if not 1 <= len(text) <= 5000:
            self.SetStatusText("请选择 1 到 5000 个字符")
            return
        if self.busy == text:
            return
        self.request_id += 1
        serial = self.request_id
        self.translation_deadline = time.monotonic() + TRANSLATION_WAIT_SECONDS
        self.busy = text
        self.go.Disable()
        self.copy.Hide()
        self.copy.GetParent().Layout()
        self.result.ChangeValue("")
        self.SetStatusText("正在翻译…")
        if self.preview.IsShown():
            self.preview.translate.Disable()
            self.preview.copy.Disable()
            self.preview.content.ChangeValue("正在翻译…")
            self.preview.set_note("仅使用你指定的文字")
        settings = dict(self.settings.values)

        def work():
            try:
                target = explicit_target(text)
                meaning, note = self.translator.translate(target, settings)
                rendered = render_markdown(meaning).text
            except TranslationError as exc:
                rendered, note = str(exc), "翻译未完成"
            except Exception:
                rendered, note = "读取翻译结果失败，请检查设置后重试。", "翻译未完成"
            if not self.closed:
                wx.CallAfter(self.finish, serial, rendered, note)
        threading.Thread(target=work, daemon=True).start()

    def finish(self, serial, text, note):
        if self.closed or serial != self.request_id or self.busy is None:
            return
        self.busy = None
        self.go.Enable()
        self.result.ChangeValue(text)
        self.copy.Show()
        self.copy.GetParent().Layout()
        self.SetStatusText(note)
        if self.preview.IsShown():
            self.preview.content.ChangeValue(text)
            self.preview.set_note(note)
            self.preview.copy.SetLabel("复制结果")
            self.preview.translate.SetLabel("重新翻译所选")
            self.preview.translate.Enable()
            self.preview.copy.Enable()

    def on_close(self, event):
        if event.CanVeto() and self.tray.IsIconInstalled():
            self.preview.Hide()
            self.Hide()
            event.Veto()
        else:
            self.quit()

    def quit(self):
        if self.closed:
            return
        self.closed = True
        self.timer.Stop()
        self.mouse.close()
        if self.hotkey:
            self.UnregisterHotKey(CLIPBOARD_HOTKEY)
        if self.toggle_hotkey:
            self.UnregisterHotKey(TOGGLE_HOTKEY)
        self.tray.RemoveIcon()
        self.tray.Destroy()
        self.preview.Destroy()
        self.Destroy()


def run():
    app = wx.App(False)
    frame = Main()
    app.SetTopWindow(frame)
    frame.Show()
    app.MainLoop()
