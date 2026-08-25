@echo off
setlocal
cd /d "%~dp0"

rem Keep standalone study output UTF-8-safe on Windows as well.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "%~dp0venv\Scripts\python.exe" (
  echo Trade Brain Python environment is not ready.
  echo Run Start-TradeBrain.bat -SetupOnly first.
  pause
  exit /b 2
)

echo.
echo Trade Brain - After Market Study
echo Kite MARKET_DATA_ONLY ^| Evidence learning ^| No broker orders
echo Keep this window open for automatic post-market study checks.
echo.

"%~dp0venv\Scripts\python.exe" -u "%~dp0scripts\tradebrain_after_market_study.py" --loop %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
  echo.
  echo Study loop exited with code %EXITCODE%.
  echo Review the Trade Brain audit TXT for details.
  pause
)

exit /b %EXITCODE%
