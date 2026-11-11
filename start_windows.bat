@echo off
chcp 65001 >nul
cd /d %~dp0
where python >nul 2>nul || (echo 没有找到 Python，请先安装 Python 3.9 以上版本：https://www.python.org/downloads/ & pause & exit /b 1)
python -m pip install -q -r requirements.txt
python run.py %*
pause
