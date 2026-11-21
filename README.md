# 指译 HoverLing

在 Linux X11 或 Windows 上划选单词、对白或段落，松开鼠标预览，点击翻译查看中文释义。默认使用离线英汉词典。想理解短语在句里的意思，可以选中整句并启用 AI 解释。

**[下载最新版（Windows x64 / Linux X11）](https://github.com/Scarlett-Qi/hoverling/releases/latest)** · [历史版本](https://github.com/Scarlett-Qi/hoverling/releases)

## 开始使用

| 平台 | 打开程序 | 卸载 |
| --- | --- | --- |
| Linux X11 / Xorg | 下载以 `-Linux-X11.zip` 结尾的包，解压后在 `hoverling` 目录运行 `bash install.sh`。在应用菜单搜索「指译」，点击「开启划词翻译」。也可直接运行 `bash launch.sh --selection`。 | 从托盘退出后，在解压包或安装目录运行 `bash uninstall.sh`。个人设置和密钥会保留。 |
| Windows 10 / 11 x64 | 下载以 `-Windows-x64.zip` 结尾的包，整个解压，双击 `HoverLing.exe`。便携包已含运行环境。 | 从托盘退出后删除解压目录。需要同时清除设置时，再删除 `%LOCALAPPDATA%\HoverLing`。 |

<details>
<summary>Linux 系统要求与依赖</summary>

使用 X11 / Xorg 会话、系统 Python 3.10+、PyGObject 和 GTK3。悬停取词还需要 Tesseract 4 或 5，包内附英文识别模型。使用 Wayland 的 Ubuntu 用户可在登录界面选择可用的 Xorg 会话。

Ubuntu 24.04 可运行以下命令，Ubuntu 22.04 将 `libtesseract5` 改为 `libtesseract4`。

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-dbusmenu-glib-0.4 libtesseract5
```
</details>

## 第一次划词

试着在浏览器中划选 **a piece of cake**，点击浮窗里的翻译按钮，离线词库就能解释“小菜一碟”。浮窗出现后约有 1.5 秒可以移入鼠标，停在浮窗内可滚动、复制，移出约半秒后收起。Windows 版可直接拖动浮窗的上边缘或下边缘调整高度，松手后会记住。

| 操作 | Linux X11 | Windows |
| --- | --- | --- |
| 读不到当前选区 | 按 `Ctrl+Alt+E`，或复制后按 `Ctrl+Alt+C` | 复制后按 `Ctrl+Alt+C`，也可在主窗口读取剪贴板或粘贴原文 |
| 暂停自动划词 | 按 `Ctrl+Alt+Y` | 主窗口点击「暂停划词翻译」 |
| 图片上的英文 | 设置中启用鼠标悬停取词，在本机做 OCR | 支持应用提供的文本选区，暂未提供屏幕 OCR |
| 托盘菜单 | 由支持 AppIndicator / StatusNotifierItem 的桌面面板显示 | 左键或右键点击通知区域图标均可打开菜单 |

托盘可用时，点主窗口的 × 可收起程序，划词继续运行。从托盘菜单可打开主界面、进入设置或退出。

## 翻译来源

Linux 在「取词与 AI 设置」启用联网翻译或 AI；两者同时开启时优先使用 AI。Windows 在「取词与 AI 设置」选择翻译服务。

| 来源 | 需要填写 | 用途 |
| --- | --- | --- |
| 离线词库 | 无 | 英语单词和已收录的短语 |
| 有道智云 | App Key、App Secret | 自动识别原文，应用需绑定文本翻译服务 |
| DeepL | DeepL API Key | 自动识别原文，支持 Free 和 Pro |
| 谷歌网页翻译 | 无需 Key | 自动识别原文，网页通道可能限流 |
| MyMemory | 原文语言 | 短文本，每次最多 480 个 UTF-8 字节 |
| AI 语境解释 | 接口地址、模型名称、API Key | 兼容 Chat Completions 的服务，可解释俚语、双关和语气 |

划选预览在本机完成，点击翻译才会向所选联网服务发送选区文字。Linux 的密钥保存在 `~/.config/hoverling/settings.json`，文件权限为 `600`。Windows 使用 `%LOCALAPPDATA%\HoverLing\settings.json`，API Key 和有道应用密钥由当前 Windows 用户的 DPAPI 加密。

从源码运行和打包请看仓库里的 `tools/README.md`。词库、OCR 模型和 Windows 运行库的授权见[第三方说明](THIRD_PARTY.md)。
