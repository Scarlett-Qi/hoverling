import wx
from .style import CANVAS, PAPER, Surface, action, divider, label, typeface, window_corners
from ..theme import CONTROL_RADIUS
from ..translate import MYMEMORY_LANGUAGES, api_url, TranslationError

MODES = {"offline": "离线英汉词典", "youdao": "有道智云", "deepl": "DeepL",
         "google_web": "谷歌网页翻译", "mymemory": "MyMemory", "ai": "AI 语境解释"}
FIELDS = {"youdao": [("youdao_app_key", "应用 ID"), ("youdao_app_secret", "应用密钥")],
          "deepl": [("deepl_api_key", "API Key")],
          "ai": [("api_base", "接口地址（Base URL）"), ("model", "模型名称"), ("api_key", "API Key")]}


def current_mode(values):
    if values["ai_enabled"]:
        return "ai"
    if values["network_enabled"]:
        return values["network_provider"]
    return "offline"


def mode_label(values):
    return MODES[current_mode(values)]


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, settings):
        super().__init__(parent, title="取词与 AI 设置")
        window_corners(self)
        self.settings = settings
        vals = settings.values
        self.controls = {}
        self.groups = {}
        self.SetBackgroundColour(CANVAS)
        d = self.FromDIP
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(label(self, "触发方式", 11, bold=True))
        layout.AddSpacer(d(8))
        self.auto = wx.CheckBox(self, label="划选文字后显示浮窗")
        typeface(self.auto, 10)
        self.auto.SetValue(vals["trigger"] == "selection")
        layout.Add(self.auto)
        layout.AddSpacer(d(14))
        layout.Add(divider(self), 0, wx.EXPAND)
        layout.AddSpacer(d(14))
        layout.Add(label(self, "翻译服务", 11, bold=True))
        layout.AddSpacer(d(10))
        self.mode = wx.Choice(self, choices=list(MODES.values()), name="翻译服务")
        typeface(self.mode, 11)
        self.mode.SetSelection(list(MODES).index(current_mode(vals)))
        layout.Add(self.mode, 0, wx.EXPAND)
        for mode in ("youdao", "deepl", "ai", "mymemory"):
            panel = wx.Panel(self)
            panel.SetBackgroundColour(CANVAS)
            box = wx.BoxSizer(wx.VERTICAL)
            for key, field_name in FIELDS.get(mode, []):
                box.AddSpacer(d(10))
                box.Add(label(panel, field_name))
                box.AddSpacer(d(4))
                secret = key in ("api_key", "youdao_app_secret", "deepl_api_key")
                field_box = Surface(panel, radius=CONTROL_RADIUS)
                control = wx.TextCtrl(field_box, value=vals[key], name=field_name,
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
        layout.AddSpacer(d(20))
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(action(self, "取消", None, id=wx.ID_CANCEL))
        buttons.AddSpacer(d(8))
        save = action(self, "保存", None, id=wx.ID_OK, primary=True)
        save.SetDefault()
        buttons.Add(save)
        layout.Add(buttons, 0, wx.ALIGN_RIGHT)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(layout, 0, wx.ALL | wx.EXPAND, d(20))
        outer.SetMinSize(d((430, -1)))
        self.SetSizer(outer)
        self.mode.Bind(wx.EVT_CHOICE, self.refresh)
        self.Bind(wx.EVT_BUTTON, self.save, id=wx.ID_OK)
        self.refresh()
        self.CentreOnParent()

    def selected(self):
        return list(MODES)[self.mode.GetSelection()]

    def refresh(self, event=None):
        for mode, panel in self.groups.items():
            panel.Show(mode == self.selected())
        self.Layout()
        self.Fit()

    def save(self, event):
        mode = self.selected()
        values = {key: control.GetValue().strip() for key, control in self.controls.items()}
        for key, label in FIELDS.get(mode, []):
            if not values[key]:
                wx.MessageBox("请填写" + label, "设置", parent=self)
                return
        try:
            if mode == "ai":
                api_url(values["api_base"])
            values.update(ai_enabled=mode == "ai", network_enabled=mode not in ("offline", "ai"),
                          trigger="selection" if self.auto.GetValue() else "alt",
                          mymemory_source=list(MYMEMORY_LANGUAGES)[self.language.GetSelection()])
            if values["network_enabled"]:
                values["network_provider"] = mode
            self.settings.save(values)
        except (OSError, TranslationError) as exc:
            wx.MessageBox(str(exc), "无法保存设置", parent=self)
            return
        self.EndModal(wx.ID_OK)
