@echo off
REM Brain one-click launcher: starts if not running, opens browser, done.
REM This is the smart launcher for the desktop shortcut.

cd /d "%~dp0"
title Brain - launcher

REM Check if dashboard already alive
powershell.exe -NoProfile -Command "try { $r = Invoke-WebRequest 'http://127.0.0.1:7860/api/status' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>&1

if %errorlevel%==0 (
    echo Brain is already running. Opening dashboard...
    start "" "http://127.0.0.1:7860"
    timeout /t 2 >nul
    exit /b 0
)

echo.
echo  ================================================
echo                B R A I N   start
echo  ================================================
echo.
echo  Starting Ollama, dashboard, tray...
echo.

call "%~dp0start.cmd"

echo.
echo  Waiting for dashboard to come up...

REM Wait up to 30s for dashboard to respond
for /l %%i in (1,1,30) do (
    powershell.exe -NoProfile -Command "try { $r = Invoke-WebRequest 'http://127.0.0.1:7860/api/status' -UseBasicParsing -TimeoutSec 1; exit 0 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 goto :ready
    timeout /t 1 >nul
)

echo  WARNING: dashboard did not respond after 30s. Check logs.
pause
exit /b 1

:ready
echo  [ok] Dashboard ready.
start "" "http://127.0.0.1:7860"
timeout /t 2 >nul
exit /b 0
