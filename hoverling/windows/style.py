"""Shared typography and native controls for the Windows client."""
import ctypes
from ctypes import wintypes
from functools import lru_cache

import wx

from ..theme import ACCENT, CANVAS, CARD_RADIUS, CONTROL_RADIUS, INK, LINE, MUTED, PAPER


def window_corners(window, *, small=False):
    # The Desktop Window Manager can decline this hint on older systems.
    try:
        apply = ctypes.windll.dwmapi.DwmSetWindowAttribute
        apply.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        apply.restype = ctypes.c_long
        preference = ctypes.c_int(3 if small else 2)
        apply(window.GetHandle(), 33, ctypes.byref(preference), ctypes.sizeof(preference))
    except (AttributeError, OSError):
        pass


@lru_cache(maxsize=1)
def chinese_ui_face():
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "Droid Sans Fallback"):
        if wx.FontEnumerator.IsValidFacename(name):
            return name
    return None


def typeface(window, points, bold=False):
    font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    face = chinese_ui_face()
    if face:
        font.SetFaceName(face)
    font.SetPointSize(points)
    if bold:
        font.SetWeight(wx.FONTWEIGHT_BOLD)
    window.SetFont(font)


def label(parent, text, points=10, colour=INK, bold=False):
    control = wx.StaticText(parent, label=text)
    typeface(control, points, bold)
    control.SetForegroundColour(colour)
    return control


class Surface(wx.Panel):
    """A rounded background for native text controls."""
    def __init__(self, parent, *, radius=CARD_RADIUS):
        super().__init__(parent)
        self.radius = radius
        self.focused = False
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(PAPER)
        self.Bind(wx.EVT_PAINT, self.paint)

    def watch_input(self, field):
        field.Bind(wx.EVT_SET_FOCUS, self.focus)
        field.Bind(wx.EVT_KILL_FOCUS, self.focus)

    def focus(self, event):
        self.focused = event.GetEventType() == wx.EVT_SET_FOCUS.typeId
        self.Refresh(False)
        event.Skip()

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        width, height = self.GetClientSize()
        gc.SetBrush(wx.Brush(PAPER))
        gc.SetPen(wx.Pen(LINE))
        gc.DrawRoundedRectangle(0.5, 0.5, max(1, width-1), max(1, height-1), self.FromDIP(self.radius))
        if self.focused:
            gc.SetPen(wx.Pen(ACCENT, self.FromDIP(2)))
            margin = self.FromDIP(self.radius)
            gc.StrokeLine(margin, height-1, width-margin, height-1)


class ActionButton(wx.Button):
    """Use the Windows button for input and accessibility, paint its face locally."""
    def __init__(self, parent, text, id, primary, quiet):
        super().__init__(parent, id=id, label=text, style=wx.BU_EXACTFIT | wx.BORDER_NONE)
        self.primary = primary
        self.quiet = quiet
        typeface(self, 10)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        d = self.FromDIP
        self.SetMinSize(wx.Size(max(d(32), self.GetTextExtent(text).width + d(26)), d(32)))
        self.Bind(wx.EVT_PAINT, self.paint)
        for event in (wx.EVT_ENTER_WINDOW, wx.EVT_LEAVE_WINDOW, wx.EVT_LEFT_DOWN, wx.EVT_LEFT_UP,
                      wx.EVT_KEY_DOWN, wx.EVT_KEY_UP, wx.EVT_SET_FOCUS, wx.EVT_KILL_FOCUS):
            self.Bind(event, self.redraw)

    def Enable(self, enable=True):
        changed = super().Enable(enable)
        if changed:
            self.Refresh(False)
        return changed

    def SetLabel(self, text):
        super().SetLabel(text)
        self.Refresh(False)

    def redraw(self, event):
        # MSW can draw a button directly while processing focus/default changes.
        # Request our paint after that native input handler has returned.
        wx.CallAfter(self.repaint_if_alive)
        event.Skip()

    def repaint_if_alive(self):
        if self:
            self.Refresh(False)

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        background = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        width, height = self.GetClientSize()
        hot = self.GetScreenRect().Contains(wx.GetMousePosition())
        # BM_GETSTATE includes BST_PUSHED for mouse and keyboard activation.
        pressed = bool(ctypes.windll.user32.SendMessageW(wintypes.HWND(self.GetHandle()), 0xF2, 0, 0) & 4)
        if not self.IsEnabled():
            fill, edge, text = "#EEEEEE", "#E5E5E5", "#787878"
        elif self.primary:
            fill = "#105D50" if pressed else "#198775" if hot else ACCENT
            edge, text = fill, PAPER
        else:
            fill = "#EAEAEA" if pressed else "#F5F5F5" if hot else background if self.quiet else "#F3F3F3"
            edge, text = (fill if self.quiet else "#E4E8EB"), INK
        gc.SetBrush(wx.Brush(fill))
        gc.SetPen(wx.Pen(edge))
        gc.DrawRoundedRectangle(.5, .5, width-1, height-1, self.FromDIP(CONTROL_RADIUS))
        if self.HasFocus():
            gc.SetBrush(wx.TRANSPARENT_BRUSH)
            gc.SetPen(wx.Pen(PAPER if self.primary else INK, self.FromDIP(1)))
            gc.DrawRoundedRectangle(2.5, 2.5, width-5, height-5, self.FromDIP(CONTROL_RADIUS - 2))
        gc.Flush()
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(wx.Colour(text))
        dc.DrawLabel(self.GetLabelText(), self.GetClientRect(), wx.ALIGN_CENTER)


def action(parent, text, handler, *, primary=False, quiet=False, id=wx.ID_ANY):
    control = ActionButton(parent, text, id, primary, quiet)
    if handler is not None:
        control.Bind(wx.EVT_BUTTON, lambda event: handler())
    return control


def divider(parent):
    line = wx.Panel(parent)
    line.SetBackgroundColour(LINE)
    line.SetMinSize(parent.FromDIP((-1, 1)))
    return line


class ReadingField(wx.TextCtrl):
    """Keep the scroll affordance when a multiline field overflows."""
    def __init__(self, parent, name, style):
        super().__init__(parent, style=style, name=name)
        self.scroll_pending = False
        self.Bind(wx.EVT_SIZE, self.on_layout)
        self.Bind(wx.EVT_TEXT, self.on_layout)

    def on_layout(self, event):
        self.schedule_scrollbar()
        event.Skip()

    def ChangeValue(self, value):
        super().ChangeValue(value)
        self.schedule_scrollbar()

    def schedule_scrollbar(self):
        if not self.scroll_pending:
            self.scroll_pending = True
            wx.CallAfter(self.update_scrollbar)

    def update_scrollbar(self):
        if not self:
            return
        self.scroll_pending = False
        hwnd = wintypes.HWND(self.GetHandle())
        # EM_GETLINECOUNT includes soft-wrapped display lines on Windows.
        lines = ctypes.windll.user32.SendMessageW(hwnd, 0xBA, 0, 0)
        line_height = max(1, self.GetCharHeight() + self.FromDIP(2))
        overflow = lines * line_height > self.GetClientSize().height - self.FromDIP(4)
        # EM_SHOWSCROLLBAR updates the Rich Edit control's own scroll state.
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -16)
        if bool(style & 0x00200000) != overflow:  # WS_VSCROLL
            ctypes.windll.user32.SendMessageW(hwnd, 0x460, 1, int(overflow))


def reading_field(parent, name, *, editable=False):
    style = wx.TE_MULTILINE | wx.TE_RICH2 | wx.BORDER_NONE
    if not editable:
        style |= wx.TE_READONLY
    field = ReadingField(parent, name, style)
    typeface(field, 11)
    field.SetBackgroundColour(parent.GetBackgroundColour())
    field.SetForegroundColour(INK)
    return field
