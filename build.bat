@echo off
setlocal
REM Builds the standalone Windows app: dist\TTSPython\TTSPython.exe
REM and dist\TTSPython-<version>-windows-x64.zip. Uses .venv if it exists.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install -r requirements.txt "pyinstaller>=6.10" || goto :fail
"%PY%" packaging\build.py %* || goto :fail
exit /b 0
:fail
echo Build failed.
exit /b 1
