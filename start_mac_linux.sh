#!/bin/sh
cd "$(dirname "$0")"
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python
command -v $PY >/dev/null 2>&1 || { echo "没有找到 Python，请先安装 Python 3.9 以上版本"; exit 1; }
$PY -m pip install -q -r requirements.txt 2>/dev/null || $PY -m pip install -q --user -r requirements.txt
exec $PY run.py "$@"
