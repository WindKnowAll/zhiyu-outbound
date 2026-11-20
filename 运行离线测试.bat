@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv
  if errorlevel 1 python -m venv .venv
)
call .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe scripts\preflight.py
if errorlevel 1 goto fail
.venv\Scripts\python.exe scripts\run_final_check.py --output reports\latest
echo 报告在 reports\latest 。真实接口请手动运行：python scripts\smoke_test.py
pause
goto end
:fail
echo 离线测试没有跑完。
pause
:end
