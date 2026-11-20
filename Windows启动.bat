@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv
  if errorlevel 1 python -m venv .venv
)
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe scripts\preflight.py
if errorlevel 1 goto fail
echo 即将启动网页。没有 .env 时只能看到缺密钥提示，不会拨打真实电话。
.venv\Scripts\python.exe -m zhiyu.server
goto end
:fail
echo 启动失败。请看上面的文字。
pause
:end
