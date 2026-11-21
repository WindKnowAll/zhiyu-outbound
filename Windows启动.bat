@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"

if exist "%PY%" goto have_py
echo No .venv yet. Creating it with py -3.12 only.
py -3.12 -m venv "%~dp0.venv"
if errorlevel 1 goto fail_venv

:have_py
call "%PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto fail
call "%PY%" "%~dp0scripts\preflight.py"
if errorlevel 1 goto fail
call "%PY%" "%~dp0scripts\reuse_listen.py" --port 7860
if errorlevel 12 goto stale
if errorlevel 11 goto occupied
if errorlevel 10 goto already
if errorlevel 1 goto fail

echo.
echo Starting the page. Without .env you only see the missing-key message.
echo Stop the server with Ctrl+C. This window stays open after it exits.
call "%PY%" -m zhiyu.server
set "EXITCODE=%ERRORLEVEL%"
echo.
echo Server stopped. Exit code %EXITCODE%.
pause
exit /b %EXITCODE%

:already
echo.
echo Already running. Use http://127.0.0.1:7860
echo This script did not start a second process.
pause
exit /b 0

:stale
echo.
echo 7860 is still serving an older page.
echo Stop that black window with Ctrl+C, then double-click this file again.
echo Refreshing the browser is not enough. The footer must show zhiyu-20261121e.
pause
exit /b 12

:occupied
echo.
echo Port 7860 is used by another program.
echo This script did not stop that process and did not change the port.
pause
exit /b 11

:fail_venv
echo.
echo FAILED: py -3.12 could not create .venv. This script does not fall back to py -3.
pause
exit /b 1

:fail
set "EXITCODE=%ERRORLEVEL%"
echo.
echo FAILED. Exit code %EXITCODE%.
pause
exit /b %EXITCODE%
