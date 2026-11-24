import wx
from .style import CANVAS, PAPER, Surface, action, label, typeface, window_corners
from .. import __version__
from ..updates import start_update_check
from ..profiles import AIProfiles
from ..theme import CONTROL_RADIUS
from ..translate import MYMEMORY_LANGUAGES, api_url, TranslationError

PROVIDERS = {"deepl": "DeepL", "youdao": "有道智云", "google_cloud": "Google Cloud 翻译",
             "doubao": "豆包翻译 · 火山方舟", "mymemory": "MyMemory"}
PROVIDER_NOTES = {
    "doubao": "使用豆包翻译模型自动识别原文并译为中文。",
    "deepl": "自动识别原文，使用 DeepL API Key。",
    "youdao": "自动识别原文，使用有道文本翻译应用的 ID 和密钥。",
    "google_cloud": "自动识别原文，用量计入密钥所属的 Google Cloud 项目。",
    "mymemory": "请选择原文语言，再译为简体中文。",
}
FIELDS = {"youdao": [("youdao_app_key", "应用 ID"), ("youdao_app_secret", "应用密钥")],
          "doubao": [("doubao_api_key", "火山方舟 API Key")],
          "google_cloud": [("google_cloud_key", "Cloud Translation API Key")],
          "deepl": [("deepl_api_key", "API Key")],
          "ai": [("api_base", "接口地址（Base URL）"), ("model", "模型名称"), ("api_key", "API Key")]}


def current_mode(values):
    if values["ai_enabled"]:
        return "ai"
    if values["network_enabled"]:
        return values["network_provider"]
    return "offline"


def mode_label(values):
    mode = current_mode(values)
    if mode == "ai":
        return "AI 语境解释"
    if mode == "offline":
        return "离线英汉词典"
    return PROVIDERS[mode]


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, settings):
        super().__init__(parent, title="取词与 AI 设置", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        window_corners(self)
        self.settings = settings
        vals = settings.values
        self.profiles = AIProfiles(vals)
        self.controls = {}
        self.groups = {}
        self.SetBackgroundColour(CANVAS)
        d = self.FromDIP
        self.scroll = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.scroll.SetBackgroundColour(CANVAS)
        self.scroll.SetScrollRate(0, d(12))
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(label(self.scroll, "触发方式", 11, bold=True))
        layout.AddSpacer(d(8))
        self.auto = wx.CheckBox(self.scroll, label="划选文字后显示浮窗")
        typeface(self.auto, 10)
        self.auto.SetValue(vals["trigger"] == "selection")
        layout.Add(self.auto)
        layout.AddSpacer(d(14))
        self.ai = wx.CheckBox(self.scroll, label="启用 AI：结合上下文解释短语、俚语与特殊含义")
        self.ai.SetValue(vals["ai_enabled"])
        typeface(self.ai, 10)
        layout.Add(self.ai)
        layout.AddSpacer(d(10))
        self.network = wx.CheckBox(self.scroll, label="启用联网翻译（发送你指定的文字）")
        self.network.SetValue(vals["network_enabled"])
        typeface(self.network, 10)
        layout.Add(self.network)
        layout.AddSpacer(d(10))
        self.provider = wx.Choice(self.scroll, choices=list(PROVIDERS.values()), name="联网翻译来源")
        typeface(self.provider, 11)
        self.provider.SetSelection(list(PROVIDERS).index(vals["network_provider"]))
        layout.Add(self.provider, 0, wx.EXPAND)
        layout.AddSpacer(d(8))
        self.note = label(self.scroll, "")
        layout.Add(self.note, 0, wx.EXPAND)
        for mode in (*PROVIDERS, "ai"):
            panel = wx.Panel(self.scroll)
            panel.SetBackgroundColour(CANVAS)
            box = wx.BoxSizer(wx.VERTICAL)
            fields = FIELDS.get(mode, [])
            if mode == "ai":
                box.AddSpacer(d(10))
                box.Add(label(panel, "两项同时启用时优先使用 AI。", 10))
                box.AddSpacer(d(8))
                row = wx.BoxSizer(wx.HORIZONTAL)
                row.Add(label(panel, "AI 配置"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, d(6))
                self.profile_choice = wx.Choice(panel, name="AI 配置")
                row.Add(self.profile_choice, 1, wx.ALIGN_CENTER_VERTICAL)
                row.Add(action(panel, "新增", self.add_profile), 0, wx.LEFT, d(6))
                self.remove_button = action(panel, "移除", self.remove_profile)
                row.Add(self.remove_button, 0, wx.LEFT, d(6))
                box.Add(row, 0, wx.EXPAND)
                fields = [("name", "配置名称"), *fields]
            for key, field_name in fields:
                box.AddSpacer(d(10))
                box.Add(label(panel, field_name))
                box.AddSpacer(d(4))
                secret = key in ("api_key", "youdao_app_secret", "deepl_api_key", "google_cloud_key", "doubao_api_key")
                field_box = Surface(panel, radius=CONTROL_RADIUS)
                control = wx.TextCtrl(field_box, value=self.profiles.current[key] if mode == "ai" else vals[key], name=field_name,
                                      style=wx.BORDER_NONE | (wx.TE_PASSWORD if secret else 0))
                typeface(control, 11)
                control.SetBackgroundColour(PAPER)
                field_box.watch_input(control)
                inner = wx.BoxSizer(wx.VERTICAL)
                inner.Add(control, 0, wx.ALL | wx.EXPAND, d(7))
                field_box.SetSizer(inner)
                box.Add(field_box, 0, wx.EXPAND)
                self.controls[key] = control
            if mode == "mymemory":
                box.AddSpacer(d(10))
                box.Add(label(panel, "原文语言"))
                box.AddSpacer(d(4))
                self.language = wx.Choice(panel, choices=list(MYMEMORY_LANGUAGES.values()), name="原文语言")
                self.language.SetSelection(list(MYMEMORY_LANGUAGES).index(vals["mymemory_source"]))
                box.Add(self.language, 0, wx.EXPAND)
            panel.SetSizer(box)
            layout.Add(panel, 0, wx.EXPAND)
            self.groups[mode] = panel
        layout.AddSpacer(d(12))
        about = wx.BoxSizer(wx.HORIZONTAL)
        about.Add(label(self.scroll, f"指译 HoverLing v{__version__}", 9), 0, wx.ALIGN_CENTER_VERTICAL)
        about.AddStretchSpacer()
        self.release_url = None
        self.update_button = action(self.scroll, "检查更新", self.check_updates)
        about.Add(self.update_button, 0, wx.ALIGN_CENTER_VERTICAL)
        layout.Add(about, 0, wx.EXPAND)
        contents = wx.BoxSizer(wx.VERTICAL)
        contents.Add(layout, 0, wx.ALL | wx.EXPAND, d(18))
        self.scroll.SetSizer(contents)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(action(self, "取消", None, id=wx.ID_CANCEL))
        buttons.AddSpacer(d(8))
        save = action(self, "保存", None, id=wx.ID_OK, primary=True)
        save.SetDefault()
        buttons.Add(save)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.scroll, 1, wx.EXPAND)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, d(12))
        self.SetSizer(outer)
        area = wx.Display(max(0, wx.Display.GetFromWindow(parent or self))).GetClientArea()
        width, height = d((520, 620))
        self.SetSize((min(width, area.width), min(height, area.height)))
        self.SetMinSize((min(d(420), area.width), min(d(320), area.height)))
        self.profile_choice.Bind(wx.EVT_CHOICE, self.switch_profile)
        self.controls["name"].Bind(wx.EVT_TEXT, self.rename_profile)
        self.refresh_profiles()
        self.provider.Bind(wx.EVT_CHOICE, self.refresh)
        self.ai.Bind(wx.EVT_CHECKBOX, self.refresh)
        self.Bind(wx.EVT_BUTTON, self.save, id=wx.ID_OK)
        self.refresh()
        self.CentreOnParent()

    def check_updates(self):
        if self.release_url:
            if wx.LaunchDefaultBrowser(self.release_url):
                self.update_checked("检查更新", None)
            else:
                self.update_checked("重试打开新版", self.release_url)
            return
        self.update_checked("正在检查…", None)
        self.update_button.Disable()
        start_update_check(wx.CallAfter, self.update_checked)

    def update_checked(self, message, url):
        if not self or self.IsBeingDeleted():
            return
        self.release_url = url
        button = self.update_button
        button.SetLabel(message)
        button.SetMinSize((button.GetTextExtent(message).width + button.FromDIP(26), button.FromDIP(32)))
        button.Enable()
        self.scroll.Layout()
        self.scroll.FitInside()

    def store_profile(self):
        for key in self.profiles.current:
            self.profiles.current[key] = self.controls[key].GetValue().strip()

    def refresh_profiles(self):
        self.profile_choice.SetItems(self.profiles.labels())
        self.profile_choice.SetSelection(self.profiles.index)
        for key, value in self.profiles.current.items():
            self.controls[key].ChangeValue(value)
        self.remove_button.Enable(len(self.profiles.items) > 1)

    def rename_profile(self, event):
        self.profiles.current["name"] = self.controls["name"].GetValue().strip()
        self.profile_choice.SetString(self.profiles.index, self.profiles.labels()[self.profiles.index])

    def switch_profile(self, event):
        self.store_profile()
        self.profiles.index = self.profile_choice.GetSelection()
        self.refresh_profiles()

    def add_profile(self):
        self.store_profile()
        self.profiles.add()
        self.refresh_profiles()
        self.controls["name"].SetFocus()
        self.controls["name"].SelectAll()

    def remove_profile(self):
        self.profiles.remove()
        self.refresh_profiles()

    def selected_provider(self):
        return list(PROVIDERS)[self.provider.GetSelection()]

    def refresh(self, event=None):
        provider = self.selected_provider()
        self.note.SetLabel(PROVIDER_NOTES[provider])
        for mode, panel in self.groups.items():
            panel.Show(self.ai.GetValue() if mode == "ai" else mode == provider)
        self.Layout()
        self.scroll.Layout()
        self.scroll.FitInside()

    def save(self, event):
        provider = self.selected_provider()
        self.store_profile()
        values = self.profiles.settings()
        values.update({key: control.GetValue().strip() for key, control in self.controls.items()
                       if key not in self.profiles.current})
        values.update(ai_enabled=self.ai.GetValue(), network_enabled=self.network.GetValue(),
                      network_provider=provider, trigger="selection" if self.auto.GetValue() else "alt",
                      mymemory_source=list(MYMEMORY_LANGUAGES)[self.language.GetSelection()])
        mode = current_mode(values)
        try:
            for key, field_name in FIELDS.get(mode, []):
                if not values[key]:
                    raise TranslationError("请填写" + field_name)
            if mode == "ai":
                api_url(values["api_base"])
            self.settings.save(values)
        except (OSError, TranslationError) as exc:
            wx.MessageBox(str(exc), "无法保存设置", parent=self)
            return
        self.EndModal(wx.ID_OK)
