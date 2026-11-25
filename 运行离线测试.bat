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
call "%PY%" -m pip install -r "%~dp0requirements-dev.txt"
if errorlevel 1 goto fail
call "%PY%" "%~dp0scripts\preflight.py"
if errorlevel 1 goto fail
call "%PY%" "%~dp0scripts\run_final_check.py" --output "%~dp0reports\latest"
if errorlevel 1 goto fail

echo.
echo OFFLINE CHECK PASSED. Report: reports\latest
echo Paid APIs were not called.
pause
exit /b 0

:fail_venv
echo.
echo FAILED: py -3.12 could not create .venv. This script does not fall back to py -3.
pause
exit /b 1

:fail
set "EXITCODE=%ERRORLEVEL%"
echo.
echo OFFLINE CHECK FAILED. Exit code %EXITCODE%.
echo This is not a pass.
pause
exit /b %EXITCODE%
