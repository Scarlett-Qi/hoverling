#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(readlink -f -- "$0")")"
export PYTHONDONTWRITEBYTECODE=1
if ! /usr/bin/python3 -c 'import gi; gi.require_version("Gtk", "3.0")' >/dev/null 2>&1; then
  echo '缺少 GTK3 / Python GObject。Ubuntu / Debian 请执行：'
  echo 'sudo apt install python3-gi gir1.2-gtk-3.0 libtesseract5'
  echo 'Ubuntu 22.04 使用 libtesseract4 代替 libtesseract5。'
  exit 1
fi
exec /usr/bin/python3 -m hoverling "$@"
