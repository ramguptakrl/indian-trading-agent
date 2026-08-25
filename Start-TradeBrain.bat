@echo off
setlocal
cd /d "%~dp0"

rem Force UTF-8 for every Python process launched by the Windows supervisor.
rem This prevents Windows cp1252/charmap crashes when model text contains
rem Unicode such as non-breaking hyphens, arrows, or other research symbols.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-TradeBrain.ps1" %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
  echo.
  echo Trade Brain exited with code %EXITCODE%.
  echo Review .tradebrain\logs for details.
  pause
)

exit /b %EXITCODE%
