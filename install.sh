#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(readlink -f -- "$0")")"
/usr/bin/python3 - <<'PY'
import os, pathlib, shutil
source = pathlib.Path.cwd().resolve()
data = pathlib.Path(os.environ.get('XDG_DATA_HOME') or pathlib.Path.home() / '.local/share')
if not data.is_absolute():
    raise SystemExit('XDG_DATA_HOME 应为绝对路径，请检查后重试。')
target = data / 'hoverling'
if source != target.resolve():
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
launcher = target / 'launch.sh'
launcher.chmod(0o755)
applications = data / 'applications'
applications.mkdir(parents=True, exist_ok=True)
def quoted(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$') + '"'
desktop = applications / 'hoverling.desktop'
desktop.write_text('[Desktop Entry]\nType=Application\nName=指译 HoverLing\n'
                   'Comment=划选文字、多语言翻译与短语解释\n'
                   'Exec=' + quoted(launcher) + '\nIcon=' + str(target / 'icon.svg') +
                   '\nStartupWMClass=HoverLing\nTerminal=false\nCategories=Utility;\nStartupNotify=false\n', encoding='utf-8')
desktop.chmod(0o644)
print('安装完成。在应用菜单搜索“指译”或“HoverLing”即可打开。')
print('安装目录：' + str(target))
print('卸载时请关闭指译，然后在解压包的目录里运行 bash uninstall.sh。')
PY
