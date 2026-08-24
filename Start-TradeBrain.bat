@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-TradeBrain.ps1" %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
  echo.
  echo Trade Brain exited with code %EXITCODE%.
  echo Review .tradebrain\logs for details.
  pause
)

exit /b %EXITCODE%
