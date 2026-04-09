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

call :CheckPackage pyttsx3
call :CheckPackage pywin32
call :CheckPackage numpy
call :CheckPackage sounddevice
call :CheckPackage faster-whisper

echo =========================================
echo Complete.
echo Missing packages were installed when possible.
echo =========================================
echo.
exit /b 0

:no_python
echo [ERROR] Python launcher (py) not found in PATH.
echo Install Python and run this script again.
exit /b 1

:CheckPackage
set "PKG=%~1"
echo Checking %PKG%...
py -m pip show "%PKG%" >nul 2>&1
if errorlevel 1 (
  echo   MISSING - installing...
  py -m pip install "%PKG%"
  if errorlevel 1 (
    echo   [ERROR] Install failed for %PKG%
    exit /b 1
  )
  py -m pip show "%PKG%" | findstr /b /c:"Name:" /c:"Version:"
) else (
  py -m pip show "%PKG%" | findstr /b /c:"Name:" /c:"Version:"
)
echo.
exit /b 0
