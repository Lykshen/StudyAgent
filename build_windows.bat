@echo off
chcp 65001 >nul
cd /d %~dp0
echo [1/3] 检查 Python ...
where python >nul 2>nul || (echo 没有找到 Python。请先安装 Python 3.9 以上版本，安装时勾选 Add to PATH。 & pause & exit /b 1)
echo [2/3] 安装打包工具（第一次需要几分钟）...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt pywebview pyinstaller || (echo 安装失败，请检查网络 & pause & exit /b 1)
echo [3/3] 打包 StudyAgent.exe ...
python -m PyInstaller --noconfirm --clean packaging\StudyAgent.spec || (echo 打包失败 & pause & exit /b 1)
echo.
echo 完成：dist\StudyAgent.exe
echo 双击即可使用；学习数据保存在 %%APPDATA%%\StudyAgent，更新 exe 不会丢失。
pause
