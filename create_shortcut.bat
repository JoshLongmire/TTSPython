@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "TARGET_PY=%SCRIPT_DIR%TTSPython.py"
set "SHORTCUT_PATH=%SCRIPT_DIR%TTSPython.lnk"
set "ICON_PATH=%SystemRoot%\System32\imageres.dll,14"

if not exist "%TARGET_PY%" (
  echo [ERROR] Could not find TTSPython.py in:
  echo %SCRIPT_DIR%
  exit /b 1
)

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python launcher "py" was not found in PATH.
  exit /b 1
)

echo Creating shortcut in this folder:
echo %SCRIPT_DIR%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$w=New-Object -ComObject WScript.Shell; " ^
  "$s=$w.CreateShortcut('%SHORTCUT_PATH%'); " ^
  "$s.TargetPath='py'; " ^
  "$s.Arguments='\"%TARGET_PY%\"'; " ^
  "$s.WorkingDirectory='%SCRIPT_DIR%'; " ^
  "$s.IconLocation='%ICON_PATH%'; " ^
  "$s.Description='Launch TTSPython app'; " ^
  "$s.Save()"

if errorlevel 1 (
  echo [ERROR] Failed to create shortcut.
  exit /b 1
)

if not exist "%SHORTCUT_PATH%" (
  echo [ERROR] Shortcut was not created at expected path:
  echo %SHORTCUT_PATH%
  exit /b 1
)

echo Shortcut created:
echo %SHORTCUT_PATH%
echo.
echo Opening folder so you can verify it now...
explorer "%SCRIPT_DIR%"
exit /b 0
