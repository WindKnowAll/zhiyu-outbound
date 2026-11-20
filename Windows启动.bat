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

echo.
echo Starting the page. Without .env you only see the missing-key message.
echo Stop the server with Ctrl+C. This window stays open after it exits.
call "%PY%" -m zhiyu.server
set "EXITCODE=%ERRORLEVEL%"
echo.
echo Server stopped. Exit code %EXITCODE%.
pause
exit /b %EXITCODE%

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
