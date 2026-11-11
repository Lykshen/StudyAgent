#!/bin/sh
# macOS: produces dist/StudyAgent.app
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt pywebview pyinstaller || exit 1
python3 -m PyInstaller --noconfirm --clean packaging/StudyAgent.spec || exit 1
echo "完成：dist/StudyAgent.app（首次打开如被拦截：系统设置 → 隐私与安全性 → 仍要打开）"
