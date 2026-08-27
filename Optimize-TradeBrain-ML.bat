@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "%~dp0venv\Scripts\python.exe" (
  echo Trade Brain Python environment is not ready.
  echo Run Start-TradeBrain.bat -SetupOnly first.
  pause
  exit /b 2
)

echo.
echo Trade Brain v0.14 - BSE ML Optimizer
echo Audited Kite history ^| Chronological validation ^| No broker orders
echo.

"%~dp0venv\Scripts\python.exe" -u "%~dp0scripts\tradebrain_ml_optimizer.py" %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
  echo.
  echo ML optimizer exited with code %EXITCODE%.
  echo Review TRADEBRAIN_DATA_DIR\ml_runs and ml_registry for details.
)
pause
exit /b %EXITCODE%
