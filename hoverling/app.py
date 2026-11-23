"""GTK3/X11 desktop UI. Screen captures stay in memory on this computer."""
from __future__ import annotations

import argparse
import ctypes as C
import ctypes.util
import hashlib
import os
import signal
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from . import theme
from .core import OCR, ROOT, Target, explicit_target, target_at
from .formatting import render_markdown
from .profiles import AIProfiles
from .translate import MYMEMORY_LANGUAGES, Settings, TranslationError, Translator, api_url, translate_youdao, translate_deepl

CSS = f"""
window {{ background: {theme.CANVAS}; color: {theme.INK}; }}
.card {{ background: {theme.PAPER}; border: 1px solid {theme.LINE}; border-radius: {theme.CARD_RADIUS}px; padding: {theme.CARD_PADDING}px; }}
.title {{ font-size: 22px; font-weight: bold; }}
.subtitle {{ color: {theme.MUTED}; font-size: 12px; }}
.word {{ font-size: 19px; font-weight: bold; color: {theme.WORD}; }}
.meaning {{ font-size: 14px; }}
.note {{ color: {theme.MUTED}; font-size: 11px; }}
button {{ border-radius: {theme.CONTROL_RADIUS}px; padding: 6px 12px; }}
button.suggested-action {{ background: {theme.ACCENT}; color: white; }}
entry {{ border-radius: {theme.CONTROL_RADIUS}px; padding: 6px; }}
""".encode("ascii")


def label(text="", style="", wrap=True):
    widget = Gtk.Label(label=text)
    widget.set_xalign(0)
    widget.set_line_wrap(wrap)
    widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if style:
        widget.get_style_context().add_class(style)
    return widget


class KeyState:
    """Observe Ctrl+Alt+Y without grabbing keys or interfering with applications."""
    def __init__(self):
        self.lib = C.CDLL(ctypes.util.find_library("X11"))
        self.lib.XOpenDisplay.argtypes = [C.c_char_p]
        self.lib.XOpenDisplay.restype = C.c_void_p
        self.lib.XKeysymToKeycode.argtypes = [C.c_void_p, C.c_ulong]
        self.lib.XKeysymToKeycode.restype = C.c_ubyte
        self.lib.XQueryKeymap.argtypes = [C.c_void_p, C.c_void_p]
        self.lib.XQueryKeymap.restype = C.c_int
        self.lib.XCloseDisplay.argtypes = [C.c_void_p]
        self.display = self.lib.XOpenDisplay(None)
        self.codes = {}

    def pressed(self, letter="y"):
        if not self.display:
            return False
        if letter not in self.codes:
            self.codes[letter] = self.lib.XKeysymToKeycode(self.display, ord(letter))
        key = self.codes[letter]
        if not key:
            return False
        keys = C.create_string_buffer(32)
        self.lib.XQueryKeymap(self.display, keys)
        return bool(keys.raw[key // 8] & (1 << (key % 8)))

    def close(self):
        if self.display:
            self.lib.XCloseDisplay(self.display)
            self.display = None


class App:
    def __init__(self, config: Settings | None = None):
        self.settings = config or Settings()
        self.display = Gdk.Display.get_default()
        self.pointer = self.display.get_default_seat().get_pointer()
        self.root = Gdk.get_default_root_window()
        self.keys = KeyState()
        self.running = True
        self.enabled = False
        self.generation = 0
        self.cancel = threading.Event()
        self.pending = None
        self.ocr_busy = False
        self.ocr = None
        self.ocr_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hoverling-ocr")
        self.net_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hoverling-net")
        self.translator = Translator()
        self.last_position = (-1000, -1000)
        self.anchor = (-1000, -1000)
        self.still_since = time.monotonic()
        self.last_capture = 0
        self.scanned = False
        self.hotkey_down = False
        self.alt_down = False
        self.target = None
        self.shown = None
        self.tip_deadline = None
        self.manual_mode = False
        self.manual_running = False
        self.request_in_progress = False
        self.selection_preview = False
        self.selection_serial = 0
        self.selection_dirty = False
        self.selection_changed_at = 0.0
        self.selection_button_down = False
        self.selection_press = (0, 0)
        self.selection_drag = 0
        self.selection_fingerprint = None
        self.selection_hotkey_down = False
        self.clipboard_hotkey_down = False
        self.primary = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.primary.connect("owner-change", self.selection_changed)
        self._make_control()
        self._make_tip()
        self._make_tray()
        self.timer_id = GLib.timeout_add(90, self.tick)

    def _make_control(self):
        self.window = Gtk.Window(title="指译 HoverLing · Linux 桌面翻译")
        self.window.set_default_size(480, 760)
        self.window.set_border_width(22)
        self.window.connect("delete-event", self.close_control)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.window.add(box)
        box.pack_start(label("指译 HoverLing", "title"), False, False, 0)
        box.pack_start(label("自己划选文字，只翻译你选中的内容。", "subtitle"), False, False, 0)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.get_style_context().add_class("card")
        box.pack_start(card, False, False, 0)
        self.status = label("已暂停 · 点击下方按钮开启" + self.mode_label(), "meaning")
        card.pack_start(self.status, False, False, 0)
        self.toggle = Gtk.Button(label="开启" + self.mode_label())
        self.toggle.get_style_context().add_class("suggested-action")
        self.toggle.connect("clicked", lambda *_: self.set_enabled(not self.enabled))
        card.pack_start(self.toggle, False, False, 0)
        self.help_label = label(self.mode_help(), "note")
        card.pack_start(self.help_label, False, False, 0)
        selection_row = Gtk.Box(spacing=8)
        read_selection = Gtk.Button(label="读取当前划选")
        read_selection.connect("clicked", self.read_primary)
        selection_row.pack_start(read_selection, True, True, 0)
        read_clipboard = Gtk.Button(label="翻译剪贴板")
        read_clipboard.connect("clicked", self.read_clipboard)
        selection_row.pack_start(read_clipboard, True, True, 0)
        card.pack_start(selection_row, False, False, 0)
        settings = Gtk.Button(label="取词与 AI 设置")
        settings.connect("clicked", self.show_settings)
        box.pack_start(settings, False, False, 0)
        box.pack_start(label("也可以手动输入或粘贴文字（英语、日语等）", "subtitle"), False, False, 0)
        row = Gtk.Box(spacing=8)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("例如：It's a piece of cake. / いらっしゃいませ")
        self.entry.set_max_length(5000)
        self.entry.connect("activate", self.manual)
        row.pack_start(self.entry, True, True, 0)
        submit = Gtk.Button(label="翻译")
        submit.connect("clicked", self.manual)
        row.pack_start(submit, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.output = Gtk.TextView()
        self.output.set_editable(False)
        self.output.set_cursor_visible(False)
        self.output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.output.set_left_margin(12)
        self.output.set_right_margin(12)
        self.output.set_top_margin(12)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(190)
        scroll.add(self.output)
        box.pack_start(scroll, True, True, 0)
        self.output.get_buffer().set_text("先划选要翻译的文字，再点击浮窗中的“翻译选中文字”。\n\n只使用你选中的词、短语或句子，不自动加入附近文字。\n\n读不到划选时，可以复制后按 Ctrl + Alt + C，或粘贴到上方输入框。\n\n有道、DeepL、谷歌和 AI 的配置在“取词与 AI 设置”中。")
        self.close_hint = label("", "note")
        box.pack_start(self.close_hint, False, False, 0)
        self.window.show_all()

    def _make_tray(self):
        self.tray = None
        try:
            from .tray import PanelIndicator
            self.tray = PanelIndicator(ROOT / "icon.svg", [
                ("打开指译", self.open_control), ("设置", self.open_settings_from_tray),
                ("退出指译", self.quit),
            ], self.tray_changed)
        except (ImportError, ValueError, GLib.Error) as exc:
            print(f"系统托盘不可用：{exc}", file=sys.stderr)
        self.tray_changed()

    def open_control(self):
        self.window.show()
        self.window.deiconify()
        self.window.present()

    def open_settings_from_tray(self):
        self.open_control()
        for dialog in Gtk.Window.list_toplevels():
            if isinstance(dialog, Gtk.Dialog) and dialog.get_transient_for() == self.window and dialog.get_visible():
                dialog.present()
                return
        self.show_settings()

    def tray_changed(self, *_):
        if not self.running:
            return
        embedded = self.tray is not None and self.tray.connected
        self.close_hint.set_text("关闭主窗口可收起到托盘。点击顶栏图标可打开系统菜单。"
                                 if embedded else "当前桌面未连接系统托盘，关闭主窗口将退出指译。")
        if not embedded and not self.window.get_visible():
            self.open_control()

    def close_control(self, *_):
        if self.tray is None or not self.tray.connected:
            return self.quit()
        self.tip.hide()
        self.window.hide()
        return True

    def _make_tip(self):
        self.tip = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.tip.set_title("指译 · 释义")
        self.tip.set_decorated(False)
        self.tip.set_resizable(False)
        self.tip.set_skip_taskbar_hint(True)
        self.tip.set_skip_pager_hint(True)
        self.tip.set_keep_above(True)
        self.tip.set_accept_focus(False)
        self.tip.set_focus_on_map(False)
        self.tip.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.get_style_context().add_class("card")
        box.set_size_request(390, -1)
        self.tip.add(box)
        row = Gtk.Box(spacing=10)
        self.tip_title = label("", "word")
        self.tip_title.set_max_width_chars(30)
        self.tip_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.tip_title.set_lines(3)
        row.pack_start(self.tip_title, True, True, 0)
        close = Gtk.Button(label="×")
        close.set_valign(Gtk.Align.START)
        close.connect("clicked", lambda *_: self.dismiss())
        row.pack_start(close, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.tip_text = label("", "meaning")
        self.tip_text.set_max_width_chars(42)
        self.tip_text.set_selectable(True)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(330)
        scroll.add(self.tip_text)
        box.pack_start(scroll, True, True, 0)
        self.tip_source = label("", "note")
        self.tip_source.set_max_width_chars(42)
        box.pack_start(self.tip_source, False, False, 0)
        row = Gtk.Box(spacing=8)
        self.sentence_button = Gtk.Button(label="翻译上下文")
        self.sentence_button.connect("clicked", lambda *_: self.sentence())
        row.pack_start(self.sentence_button, True, True, 0)
        self.copy_button = Gtk.Button(label="复制结果")
        self.copy_button.connect("clicked", self.copy)
        row.pack_start(self.copy_button, True, True, 0)
        box.pack_start(row, False, False, 0)

    def invalidate(self):
        self.generation += 1
        self.selection_serial += 1
        self.cancel.set()
        self.cancel = threading.Event()
        self.request_in_progress = False
        if hasattr(self, "sentence_button"):
            self.sentence_button.set_sensitive(True)
        if self.pending:
            self.pending.cancel()

    def dismiss(self):
        self.invalidate()
        self.selection_preview = False
        self.tip.hide()
        self.scanned = True

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.invalidate()
        self.tip.hide()
        self.manual_running = False
        self.manual_mode = False
        self.selection_preview = False
        self.selection_dirty = False
        self.selection_button_down = False
        self.selection_drag = 0
        self.scanned = False
        self.still_since = time.monotonic()
        self.toggle.set_label(("暂停" if enabled else "开启") + self.mode_label())
        self.help_label.set_text(self.mode_help())
        if self.settings.values["trigger"] == "selection":
            self.status.set_text("划词已开启 · 划选后点浮窗中的翻译按钮" if enabled else "已暂停 · 仍可手动读取划选或剪贴板")
            if enabled:
                self.read_primary(baseline=True)
        else:
            self.status.set_text("取词中 · " + ("停留时按住 Alt" if self.settings.values["trigger"] == "alt" else "鼠标停留后自动翻译")
                                 if enabled else "已暂停 · 手动翻译仍可使用")

    def mode_label(self):
        return "划词翻译" if self.settings.values["trigger"] == "selection" else "鼠标取词"

    def mode_help(self):
        if self.settings.values["trigger"] == "selection":
            return "划选 → 松手 → 点翻译；Ctrl + Alt + E 读取划选\n复制后按 Ctrl + Alt + C；Ctrl + Alt + Y 暂停 / 恢复"
        return "Ctrl + Alt + Y 暂停 / 恢复\n也可用 Ctrl + Alt + E 读取划选，Ctrl + Alt + C 读取复制的文字"

    def selection_owned_here(self):
        return self.primary.get_owner() is not None

    def selection_changed(self, *_):
        if not self.running or not self.enabled or self.settings.values["trigger"] != "selection":
            return
        if self.selection_owned_here() or self.window.is_active():
            return
        self.invalidate()
        self.manual_running = False
        self.selection_dirty = True
        self.selection_changed_at = time.monotonic()

    def read_primary(self, *_, baseline=False):
        self.request_selected_text("primary", baseline=baseline)

    def read_clipboard(self, *_):
        self.request_selected_text("clipboard")

    def request_selected_text(self, kind, *, baseline=False, automatic=False):
        if not self.running:
            return
        if kind == "primary" and not baseline and self.selection_owned_here():
            if not automatic:
                self.status.set_text("请先在其他软件中划选文字，或复制后使用“翻译剪贴板”。")
            return
        if not baseline:
            self.invalidate()
            self.manual_mode = True
            self.manual_running = False
            self.selection_dirty = False
            if not automatic:
                self.selection_preview = False
                self.target = None
                self.tip.hide()
        self.selection_serial += 1
        _, x, y = self.pointer.get_position()
        data = (self.selection_serial, kind, baseline, automatic, (x, y))
        clipboard = self.primary if kind == "primary" else self.clipboard
        clipboard.request_text(self.selected_text_received, data)

    def selected_text_received(self, clipboard, text, data):
        serial, kind, baseline, automatic, anchor = data
        if not self.running or serial != self.selection_serial:
            return
        fingerprint = hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()
        if baseline:
            self.selection_fingerprint = fingerprint
            return
        if automatic:
            if not self.enabled or self.settings.values["trigger"] != "selection" or self.selection_owned_here():
                self.manual_mode = False
                return
            if fingerprint == self.selection_fingerprint:
                self.manual_mode = False
                return
        if kind == "primary":
            self.selection_fingerprint = fingerprint
        try:
            target = explicit_target(text or "")
        except ValueError as exc:
            self.manual_mode = False
            if not automatic or (text and text.strip()):
                self.status.set_text(str(exc))
            return
        self.stage_selection(target, anchor)

    def stage_selection(self, target, anchor):
        self.invalidate()
        self.target = target
        self.anchor = anchor
        self.manual_mode = False
        self.manual_running = False
        self.selection_preview = True
        title = target.query[:100] + ("…" if len(target.query) > 100 else "")
        self.tip_title.set_text(title)
        self.tip_title.set_tooltip_text(target.query)
        self.tip_text.set_text(target.query)
        self.tip_source.set_text("尚未联网 · 点翻译后只发送这段文字，不取附近上下文")
        self.sentence_button.set_label("翻译选中文字")
        self.copy_button.set_label("复制选中文字")
        self.output.get_buffer().set_text("选中文字（尚未发送）：\n\n" + target.query + "\n\n点击浮窗中的“翻译选中文字”继续。")
        self.status.set_text(f"已读取 {len(target.query)} 个字符 · 点浮窗中的翻译按钮")
        self.open_tip()

    def open_tip(self):
        self.tip_deadline = time.monotonic() + 1.5
        self.tip.show_all()
        self.position_tip()
        GLib.idle_add(self.position_tip)

    def tick_selection(self, x, y, state, now):
        if not self.enabled:
            self.selection_dirty = False
            self.selection_button_down = False
            return True
        pressed = bool(state & Gdk.ModifierType.BUTTON1_MASK)
        if pressed:
            if not self.selection_button_down:
                self.selection_press = (x, y)
                self.selection_drag = 0
            self.selection_button_down = True
            self.selection_drag = max(self.selection_drag, abs(x - self.selection_press[0]), abs(y - self.selection_press[1]))
            if self.selection_dirty:
                self.selection_changed_at = now
            return True
        if self.selection_button_down:
            self.selection_button_down = False
            if self.selection_drag >= 8 and not self.selection_owned_here() and not self.window.is_active():
                self.invalidate()
                self.selection_dirty = True
                self.selection_changed_at = now
        if self.selection_dirty and now - self.selection_changed_at >= 0.2:
            self.selection_dirty = False
            self.request_selected_text("primary", automatic=True)
        return True

    @staticmethod
    def inside(window, x, y, margin=0):
        if not window.get_visible() or window.get_window() is None:
            return False
        if window.get_window().get_state() & Gdk.WindowState.ICONIFIED:
            return False
        wx, wy = window.get_position()
        size = window.get_size()
        return wx - margin <= x <= wx + size.width + margin and wy - margin <= y <= wy + size.height + margin

    def tick(self):
        if not self.running:
            return False
        _, x, y = self.pointer.get_position()
        _, _, _, state = self.root.get_device_position(self.pointer)
        alt = bool(state & Gdk.ModifierType.MOD1_MASK)
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        hotkey = alt and ctrl and self.keys.pressed()
        if hotkey and not self.hotkey_down:
            self.set_enabled(not self.enabled)
        self.hotkey_down = hotkey
        now = time.monotonic()
        selection_hotkey = alt and ctrl and self.keys.pressed("e")
        clipboard_hotkey = alt and ctrl and self.keys.pressed("c")
        if selection_hotkey and not self.selection_hotkey_down:
            self.read_primary()
        if clipboard_hotkey and not self.clipboard_hotkey_down:
            self.read_clipboard()
        self.selection_hotkey_down = selection_hotkey
        self.clipboard_hotkey_down = clipboard_hotkey
        if self.tip.get_visible():
            if self.inside(self.tip, x, y):
                self.tip_deadline = None
                return True
            if self.tip_deadline is None:
                self.tip_deadline = now + 0.5
            if now >= self.tip_deadline:
                self.tip.hide()
                # Keep pending selection reads and let translations finish in the main window.
                self.last_position = (x, y)
                self.still_since = now
                self.scanned = abs(x - self.anchor[0]) < 24 and abs(y - self.anchor[1]) < 24
            elif self.settings.values["trigger"] != "selection":
                return True
        if self.settings.values["trigger"] == "selection":
            return self.tick_selection(x, y, state, now)
        moved = abs(x - self.last_position[0]) > 3 or abs(y - self.last_position[1]) > 3
        if moved:
            self.last_position = (x, y)
            self.still_since = now
            self.scanned = False
            if not self.manual_mode:
                self.invalidate()
        if not self.enabled or self.inside(self.window, x, y) or self.manual_running:
            return True
        if self.settings.values["trigger"] == "alt":
            if alt and not self.alt_down:
                self.scanned = False
                self.still_since = now
            self.alt_down = alt
            if not alt:
                return True
        if state & (Gdk.ModifierType.BUTTON1_MASK | Gdk.ModifierType.BUTTON2_MASK | Gdk.ModifierType.BUTTON3_MASK):
            self.still_since = now
            return True
        if self.scanned or self.ocr_busy or now - self.still_since < self.settings.values["delay"] / 1000 or now - self.last_capture < 1.0:
            return True
        self.manual_mode = False
        self.capture(x, y)
        return True

    def capture(self, x, y):
        self.scanned = True
        self.last_capture = time.monotonic()
        self.anchor = (x, y)
        self.tip.hide()
        # GDK coordinates and screenshot pixels can differ with HiDPI scaling.
        width, height = self.root.get_width(), self.root.get_height()
        left, top = max(0, min(x - 480, width - min(960, width))), max(0, min(y - 100, height - min(200, height)))
        w, h = min(960, width - left), min(200, height - top)
        pixbuf = Gdk.pixbuf_get_from_window(self.root, left, top, w, h)
        if pixbuf is None:
            self.status.set_text("无法读取屏幕，请确认当前是 X11 会话。")
            return
        factor = 2
        scaled = pixbuf.scale_simple(w * factor, h * factor, GdkPixbuf.InterpType.BILINEAR)
        actual_scale = scaled.get_width() / w
        image = (scaled.get_pixels(), scaled.get_width(), scaled.get_height(), scaled.get_n_channels(), scaled.get_rowstride())
        gen, cancel = self.generation, self.cancel
        self.ocr_busy = True

        def work():
            result, error = None, None
            try:
                if not cancel.is_set():
                    if self.ocr is None:
                        self.ocr = OCR()
                    words = self.ocr.recognize(*image)
                    result = target_at(words, (x - left) * actual_scale, (y - top) * actual_scale, int(3 * actual_scale))
            except Exception as exc:
                error = str(exc)
            GLib.idle_add(self.detected, result, error, gen)
        self.ocr_pool.submit(work)

    def detected(self, target, error, gen):
        self.ocr_busy = False
        if not self.running or gen != self.generation:
            return False
        if error:
            self.status.set_text(error)
            return False
        if target:
            self.target = target
            self.show_result(target, "正在翻译…", "本地 OCR · 已识别" + ("短语" if target.phrase else "单词"))
            self.start_translation(target, False, gen)
        return False

    def start_translation(self, target, sentence, gen):
        settings, cancel = dict(self.settings.values), self.cancel
        self.request_in_progress = True
        self.sentence_button.set_sensitive(False)

        def work():
            if cancel.is_set():
                return
            try:
                text, source = self.translator.translate(target, settings, sentence)
            except TranslationError as exc:
                text = str(exc)
                source = "翻译未完成" + (" · 本地短语说明仍可查看" if target.explanation else "")
            except Exception:
                text, source = "翻译未完成，请检查接口设置后重试。", "翻译服务异常"
            GLib.idle_add(self.translated, target, text, source, gen)
        self.pending = self.net_pool.submit(work)

    def translated(self, target, text, source, gen):
        if self.running and gen == self.generation:
            self.manual_running = False
            self.request_in_progress = False
            self.sentence_button.set_sensitive(True)
            self.show_result(target, text, source, show_tip=self.tip.get_visible())
            if target.explicit:
                self.status.set_text("已返回所选文字的结果 · 可继续划选其他内容")
        return False

    def show_result(self, target, text, source, *, show_tip=True):
        self.selection_preview = False
        self.sentence_button.set_label("重新翻译所选" if target.explicit else "翻译上下文")
        self.copy_button.set_label("复制结果")
        body = text
        if target.explanation and target.explanation not in text:
            body += "\n\n" + ("**短语说明（本地词库）**\n" if target.phrase else "**其他常见含义（本地词库）**\n") + target.explanation
        formatted = render_markdown(body)
        if target.explicit:
            suffix = f"\n\n{source}\n\n范围：仅使用你指定的文字"
        else:
            suffix = f"\n\n附近文字：{target.context}\n\n{source}"
        self.shown = target.query + "\n\n" + formatted.text + suffix
        buffer = Gtk.TextBuffer()
        buffer.set_text(target.query + "\n\n")
        buffer.insert_markup(buffer.get_end_iter(), formatted.markup, -1)
        buffer.insert(buffer.get_end_iter(), suffix)
        self.output.set_buffer(buffer)
        if self.manual_mode or not show_tip:
            return
        self.tip_title.set_text(target.query[:100] + ("…" if len(target.query) > 100 else ""))
        self.tip_title.set_tooltip_text(target.query)
        self.tip_text.set_markup(formatted.markup)
        self.tip_source.set_text(source)
        if not self.tip.get_visible():
            self.open_tip()
        else:
            GLib.idle_add(self.position_tip, True)

    def position_tip(self, keep_position=False):
        if not self.tip.get_visible():
            return False
        x, y = self.anchor
        monitor = self.display.get_monitor_at_point(x, y)
        area = monitor.get_workarea()
        size = self.tip.get_size()
        tx = x + 18
        ty = y + 22
        if tx + size.width > area.x + area.width:
            tx = x - size.width - 18
        if ty + size.height > area.y + area.height:
            ty = y - size.height - 20
        if keep_position:
            tx, ty = self.tip.get_position()
        self.tip.move(max(area.x, min(tx, area.x + area.width - size.width)),
                      max(area.y, min(ty, area.y + area.height - size.height)))
        return False

    def manual(self, *_):
        text = self.entry.get_text().strip()
        if not text:
            return
        if self.request_in_progress and self.target and self.target.query == text:
            self.status.set_text("正在翻译这段文字，请等待当前结果。")
            return
        try:
            target = explicit_target(text)
        except ValueError as exc:
            self.status.set_text(str(exc))
            return
        self.invalidate()
        self.tip.hide()
        self.manual_mode = True
        self.manual_running = True
        self.target = target
        self.show_result(self.target, "正在翻译…", "手动输入")
        self.start_translation(self.target, False, self.generation)

    def sentence(self):
        if self.target and self.sentence_button.get_sensitive() and not self.request_in_progress:
            self.invalidate()
            explicit = self.target.explicit
            self.start_translation(self.target, not explicit, self.generation)
            self.show_result(self.target, "正在翻译所选文字…" if explicit else "正在翻译附近上下文…",
                             "仅发送你指定的文字" if explicit else "仅发送已识别的附近文字")

    def copy(self, *_):
        if self.selection_preview and self.target:
            self.clipboard.set_text(self.target.query, -1)
        elif self.shown:
            self.clipboard.set_text(self.shown, -1)

    def show_settings(self, *_, preferred_provider=None):
        was_enabled = self.enabled
        self.set_enabled(False)
        dialog = Gtk.Dialog(title="取词与 AI 设置", transient_for=self.window, modal=True)
        dialog.set_default_size(520, 620)
        dialog.add_buttons("取消", Gtk.ResponseType.CANCEL, "保存", Gtk.ResponseType.OK)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroll.add(box)
        box.set_border_width(18)
        box.set_spacing(10)
        values = self.settings.values
        trigger = Gtk.ComboBoxText()
        trigger.append("selection", "自己划选 → 点翻译（推荐，不取附近文字）")
        trigger.append("hover", "鼠标停留即翻译")
        trigger.append("alt", "按住 Alt，再停留翻译")
        trigger.set_active_id(values["trigger"])
        box.pack_start(label("触发方式"), False, False, 0)
        box.pack_start(trigger, False, False, 0)
        box.pack_start(label("划选 / 粘贴可翻译多种语言；旧悬停 OCR 目前仅配有英文识别模型。目标语言为简体中文。", "note"), False, False, 0)
        delay = Gtk.SpinButton.new_with_range(450, 2500, 50)
        delay.set_value(values["delay"])
        box.pack_start(label("停留时间（毫秒，仅悬停模式使用）"), False, False, 0)
        box.pack_start(delay, False, False, 0)
        ai = Gtk.CheckButton(label="启用 AI：结合上下文解释短语、俚语与特殊含义")
        ai.set_active(False if preferred_provider in ("deepl", "youdao") else values["ai_enabled"])
        box.pack_start(ai, False, False, 0)
        network = Gtk.CheckButton(label="启用联网翻译（发送你指定的文字）")
        network.set_active(values["network_enabled"])
        box.pack_start(network, False, False, 0)
        provider = Gtk.ComboBoxText()
        provider.append("deepl", "DeepL · 官方文本翻译（独立 API Key）")
        provider.append("youdao", "有道智云 · 官方文本翻译（App Key / Secret）")
        provider.append("google_cloud", "Google Cloud 翻译 · 官方文本翻译")
        provider.append("mymemory", "MyMemory · 免费基础接口")
        provider.set_active_id(preferred_provider or values["network_provider"])
        box.pack_start(provider, False, False, 0)
        service_note = label("", "note")
        box.pack_start(service_note, False, False, 0)
        mymemory_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        mymemory_box.pack_start(label("MyMemory 原文语言（手动指定）", "subtitle"), False, False, 0)
        mymemory_source = Gtk.ComboBoxText()
        for code, name in MYMEMORY_LANGUAGES.items():
            mymemory_source.append(code, name)
        mymemory_source.set_active_id(values["mymemory_source"])
        mymemory_box.pack_start(mymemory_source, False, False, 0)
        box.pack_start(mymemory_box, False, False, 0)
        mymemory_box.show_all()
        mymemory_box.set_no_show_all(True)
        youdao_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(youdao_box, False, False, 0)
        youdao_fields = {}
        for key, title in (("youdao_app_key", "应用 ID（App Key）"), ("youdao_app_secret", "应用密钥（App Secret）")):
            youdao_box.pack_start(label(title, "subtitle"), False, False, 0)
            entry = Gtk.Entry(text=values[key])
            if key == "youdao_app_secret":
                entry.set_visibility(False)
                entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            youdao_fields[key] = entry
            youdao_box.pack_start(entry, False, False, 0)
        youdao_box.pack_start(label("密钥只在本机参与签名，不作为参数发送。保存后保存在本机配置文件（权限 600，未使用钥匙串加密）。", "note"), False, False, 0)
        test_button = Gtk.Button(label="测试有道连接（发送 hello，按账户额度计费）")
        test_status = label("", "note")
        youdao_box.pack_start(test_button, False, False, 0)
        youdao_box.pack_start(test_status, False, False, 0)

        def test_youdao(button):
            app_key = youdao_fields["youdao_app_key"].get_text().strip()
            app_secret = youdao_fields["youdao_app_secret"].get_text().strip()
            if not app_key or not app_secret:
                test_status.set_text("请先填写 App Key 和 App Secret。")
                return
            button.set_sensitive(False)
            test_status.set_text("正在使用 hello 测试有道连接…")

            def finished(message):
                if self.running and dialog.get_visible():
                    button.set_sensitive(True)
                    test_status.set_text(message)
                return False

            def work():
                try:
                    text = translate_youdao("hello", app_key, app_secret)
                    message = "连接成功：hello → " + text
                except TranslationError as exc:
                    message = "连接未通过：" + str(exc)
                except Exception:
                    message = "连接测试未完成，请检查配置后重试。"
                GLib.idle_add(finished, message)
            self.net_pool.submit(work)

        test_button.connect("clicked", test_youdao)
        youdao_box.show_all()
        youdao_box.set_no_show_all(True)

        deepl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(deepl_box, False, False, 0)
        deepl_box.pack_start(label("DeepL API Key（来自 API 套餐，不是登录密码）", "subtitle"), False, False, 0)
        deepl_key = Gtk.Entry(text=values["deepl_api_key"])
        deepl_key.set_visibility(False)
        deepl_key.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        deepl_box.pack_start(deepl_key, False, False, 0)
        deepl_server = Gtk.ComboBoxText()
        deepl_server.append("auto", "自动选择（按 Key 后缀识别）")
        deepl_server.append("standard", "标准接口 · api.deepl.com")
        deepl_server.append("free", "API-Free 接口 · api-free.deepl.com")
        deepl_server.set_active_id(values["deepl_server"])
        deepl_box.pack_start(deepl_server, False, False, 0)
        deepl_box.pack_start(label("自动模式：Key 以 :fx 结尾用 API-Free，其余用标准接口。若套餐另有指定，以账户提供的接口为准。无需填写模型名称或 App Secret。Key 保存于本机配置文件（权限 600）。", "note"), False, False, 0)
        deepl_box.pack_start(Gtk.LinkButton.new_with_label("https://www.deepl.com/en/pro#developer", "申请 / 管理 DeepL API 套餐"), False, False, 0)
        deepl_test = Gtk.Button(label="测试 DeepL 连接（发送 hello，计入账户额度）")
        deepl_status = label("", "note")
        deepl_box.pack_start(deepl_test, False, False, 0)
        deepl_box.pack_start(deepl_status, False, False, 0)

        def test_deepl(button):
            key = deepl_key.get_text().strip()
            server = deepl_server.get_active_id()
            if not key:
                deepl_status.set_text("请先填写 DeepL API Key。")
                return
            button.set_sensitive(False)
            deepl_status.set_text("正在使用 hello 测试 DeepL 连接…")

            def finished(message):
                if self.running and dialog.get_visible():
                    button.set_sensitive(True)
                    deepl_status.set_text(message)
                return False

            def work():
                try:
                    text = translate_deepl("hello", key, server)
                    message = "连接成功：hello → " + text
                except TranslationError as exc:
                    message = "连接未通过：" + str(exc)
                except Exception:
                    message = "连接测试未完成，请检查配置后重试。"
                GLib.idle_add(finished, message)
            self.net_pool.submit(work)

        deepl_test.connect("clicked", test_deepl)
        deepl_box.show_all()
        deepl_box.set_no_show_all(True)

        cloud_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(cloud_box, False, False, 0)
        cloud_box.pack_start(label("Cloud Translation API Key", "subtitle"), False, False, 0)
        cloud_key = Gtk.Entry(text=values["google_cloud_key"])
        cloud_key.set_visibility(False)
        cloud_key.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        cloud_box.pack_start(cloud_key, False, False, 0)
        cloud_box.show_all()
        cloud_box.set_no_show_all(True)

        def update_provider(*_):
            selected = provider.get_active_id()
            cloud_box.set_visible(selected == "google_cloud")
            youdao_box.set_visible(selected == "youdao")
            deepl_box.set_visible(selected == "deepl")
            mymemory_box.set_visible(selected == "mymemory")
            notes = {
                "deepl": "DeepL 自动识别所选文字的语言并译为简体中文。不附加选区外上下文。使用 DeepL 时请关闭“启用 AI”；否则仍优先使用 AI。",
                "youdao": "有道自动识别原文并译为简体中文。划选模式只发送所选内容，不附带附近文字。需要绑定文本翻译服务并有可用额度；AI 开启时优先使用 AI。",
                "google_cloud": "Google Cloud 自动识别原文并译为简体中文，用量计入密钥所属项目。AI 开启时优先使用 AI。",
                "mymemory": "MyMemory 需要手动选择原文语言，再译为简体中文。所查文字会发送给 MyMemory，受服务额度和网络可达性限制。AI 开启时优先使用 AI。",
            }
            service_note.set_text(notes.get(selected, ""))
        provider.connect("changed", update_provider)
        update_provider()
        ai_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(ai_box, False, False, 0)
        ai_box.pack_start(label("AI 自动识别原文语言，用简体中文翻译并解释表达；实际语种能力取决于所用模型。这里填写对话 AI 的接口、模型和 API Key。Key 保存在本机配置文件（权限 600）。", "note"), False, False, 0)
        profiles = AIProfiles(values)
        row = Gtk.Box(spacing=6)
        ai_box.pack_start(row, False, False, 0)
        row.pack_start(label("AI 配置"), False, False, 0)
        choice = Gtk.ComboBoxText()
        row.pack_start(choice, True, True, 0)
        add = Gtk.Button(label="新增")
        remove = Gtk.Button(label="移除")
        row.pack_start(add, False, False, 0)
        row.pack_start(remove, False, False, 0)
        fields = {}
        for key, title in (("name", "配置名称"), ("api_base", "接口地址（支持 Chat Completions 协议）"), ("model", "模型名称"), ("api_key", "API Key（由服务商提供，调用可能收费）")):
            ai_box.pack_start(label(title, "subtitle"), False, False, 0)
            entry = Gtk.Entry(text=profiles.current[key])
            if key == "api_key":
                entry.set_visibility(False)
                entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            fields[key] = entry
            ai_box.pack_start(entry, False, False, 0)

        def store_profile():
            profiles.current.update({key: entry.get_text().strip() for key, entry in fields.items()})

        def refresh_profiles():
            with choice.handler_block(switch_handler):
                choice.remove_all()
                for title in profiles.labels():
                    choice.append_text(title)
                choice.set_active(profiles.index)
            for key, entry in fields.items():
                entry.set_text(profiles.current[key])
            remove.set_sensitive(len(profiles.items) > 1)

        def switch_profile(combo):
            index = combo.get_active()
            if index >= 0 and index != profiles.index:
                store_profile()
                profiles.index = index
                refresh_profiles()

        def add_profile(_):
            store_profile()
            profiles.add()
            refresh_profiles()
            fields["name"].grab_focus()
            fields["name"].select_region(0, -1)

        def remove_profile(_):
            profiles.remove()
            refresh_profiles()

        def rename_profile(entry):
            profiles.current["name"] = entry.get_text().strip()
            choice.get_model()[profiles.index][0] = profiles.labels()[profiles.index]

        switch_handler = choice.connect("changed", switch_profile)
        fields["name"].connect("changed", rename_profile)
        add.connect("clicked", add_profile)
        remove.connect("clicked", remove_profile)
        refresh_profiles()
        ai_box.show_all()
        ai_box.set_no_show_all(True)
        ai_box.set_visible(ai.get_active())
        ai.connect("toggled", lambda checkbox: ai_box.set_visible(checkbox.get_active()))
        error = label("", "note")
        box.pack_start(error, False, False, 0)
        dialog.show_all()
        while dialog.run() == Gtk.ResponseType.OK:
            store_profile()
            updated = profiles.settings()
            updated.update({name: entry.get_text().strip() for name, entry in youdao_fields.items()})
            updated.update(deepl_api_key=deepl_key.get_text().strip(), deepl_server=deepl_server.get_active_id())
            updated["google_cloud_key"] = cloud_key.get_text().strip()
            updated.update(mymemory_source=mymemory_source.get_active_id())
            updated.update(delay=delay.get_value_as_int(), trigger=trigger.get_active_id(), ai_enabled=ai.get_active(), network_enabled=network.get_active(), network_provider=provider.get_active_id())
            try:
                if updated["network_enabled"] and updated["network_provider"] == "google_cloud" and not updated["ai_enabled"] and not updated["google_cloud_key"]:
                    raise TranslationError("请填写 Google Cloud Translation API Key。")
                if updated["network_enabled"] and updated["network_provider"] == "deepl" and not updated["ai_enabled"] and not updated["deepl_api_key"]:
                    raise TranslationError("使用 DeepL 翻译需要填写 DeepL API Key。")
                if updated["network_enabled"] and updated["network_provider"] == "youdao" and not updated["ai_enabled"]:
                    if not updated["youdao_app_key"] or not updated["youdao_app_secret"]:
                        raise TranslationError("使用有道翻译需要填写 App Key 和 App Secret。")
                if updated["ai_enabled"]:
                    api_url(updated["api_base"])
                    if not updated["api_key"] or not updated["model"]:
                        raise TranslationError("启用 AI 需要填写 API Key 和模型名称。")
                self.settings.save(updated)
                break
            except (TranslationError, OSError) as exc:
                error.set_text(str(exc))
        dialog.destroy()
        self.set_enabled(was_enabled)

    def quit(self):
        if not self.running:
            return True
        self.running = False
        if self.tray is not None:
            self.tray.close()
        if GLib.MainContext.default().find_source_by_id(self.timer_id):
            GLib.source_remove(self.timer_id)
        self.invalidate()
        self.ocr_pool.submit(lambda: self.ocr.close() if self.ocr else None)
        self.ocr_pool.shutdown(wait=False, cancel_futures=False)
        self.net_pool.shutdown(wait=False, cancel_futures=True)
        self.keys.close()
        self.tip.destroy()
        self.window.destroy()
        Gtk.main_quit()
        return True


def main():
    GLib.set_prgname("hoverling")
    GLib.set_application_name("指译 HoverLing")
    Gdk.set_program_class("HoverLing")
    parser = argparse.ArgumentParser(description="指译 HoverLing · Linux 桌面划词翻译")
    parser.add_argument("--settings", action="store_true", help="启动时打开设置")
    parser.add_argument("--setup-youdao", action="store_true", help="打开有道翻译设置，填写 App Key / Secret")
    parser.add_argument("--setup-deepl", action="store_true", help="打开 DeepL 设置，填写独立 API Key")
    parser.add_argument("--selection", action="store_true", help="开启划选模式，仅在点翻译后处理所选文字")
    args = parser.parse_args()
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        print("当前是 Wayland 会话。本版全局悬停取词需要 X11。\n请注销，在登录界面齿轮菜单选择 Ubuntu on Xorg 后重新登录。", file=sys.stderr)
        return 2
    if not Gtk.init_check()[0]:
        print("无法连接桌面。请在 Linux 图形桌面的终端中启动。", file=sys.stderr)
        return 2
    if "X11" not in Gdk.Display.get_default().__gtype__.name:
        print("本版需要 X11 桌面会话。", file=sys.stderr)
        return 2
    try:
        Gtk.Window.set_default_icon_from_file(str(ROOT / "icon.svg"))
    except GLib.Error as exc:
        print(f"无法加载指译图标：{exc.message}", file=sys.stderr)
    single = socket.socket(socket.AF_UNIX)
    try:
        single.bind("\0hoverling-" + str(os.getuid()))
    except OSError:
        message = Gtk.MessageDialog(message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
                                    text="指译已经在运行。请从系统托盘菜单选择“打开指译”，或切换到已打开的指译窗口。")
        message.run()
        message.destroy()
        return 0
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    app = App()
    if args.selection:
        app.settings.values["trigger"] = "selection"
        app.set_enabled(True)
    if args.settings or args.setup_youdao or args.setup_deepl:
        def open_settings():
            preferred = "deepl" if args.setup_deepl else "youdao" if args.setup_youdao else None
            app.show_settings(preferred_provider=preferred)
            return False
        GLib.idle_add(open_settings)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, app.quit)
    try:
        Gtk.main()
    finally:
        single.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
