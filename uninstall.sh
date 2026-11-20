#!/usr/bin/env bash
set -euo pipefail
if (( $# )); then
    echo '用法：bash uninstall.sh（移除指译，保留设置和密钥）' >&2
    exit 2
fi
/usr/bin/python3 - <<'PY'
import os
import shutil
from pathlib import Path

data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
if not data.is_absolute():
    raise SystemExit('XDG_DATA_HOME 应为绝对路径，请检查后重试。')
target = data / 'hoverling'
desktop = data / 'applications' / 'hoverling.desktop'
config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'hoverling'

if target.is_symlink():
    target.unlink()
elif target.exists():
    if not all((target / name).is_file() for name in ('launch.sh', 'install.sh', 'hoverling/app.py')):
        raise SystemExit(f'无法确认这是指译的安装目录，请检查：{target}')
    if config.resolve().is_relative_to(target.resolve()):
        raise SystemExit(f'配置位于安装目录内，请先移走配置再卸载：{config}')
    shutil.rmtree(target)
desktop.unlink(missing_ok=True)
print('指译的程序和应用菜单入口已移除。个人设置和 API 密钥已保留。')
PY
