@echo off
setlocal

echo =========================================
echo TTSPython dependency installer
echo =========================================
echo.
echo This script installs missing dependencies only.
echo It does NOT upgrade Python or pip.
echo.

where py >nul 2>&1
if errorlevel 1 goto no_python

echo Python version:
py -V
echo.

py -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo.
  echo [ERROR] Installing the requirements failed.
  exit /b 1
)

echo.
echo =========================================
echo Complete.
echo Run with:  py TTSPython.py
echo =========================================
echo.
exit /b 0

:no_python
echo [ERROR] Python launcher (py) not found in PATH.
echo Install Python 3.9 or newer and run this script again.
exit /b 1
