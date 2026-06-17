@echo off
setlocal enabledelayedexpansion
title Brain AI Hub - menu
cd /d "%~dp0"

:menu
cls
echo.
echo  ====================================================
echo               B R A I N    A I    H U B
echo  ====================================================
echo.
call :status_line
echo.
echo  ----------------------------------------------------
echo    [1]  START      launch all services
echo    [2]  STOP       stop everything
echo    [3]  RESTART    stop then start
echo    [4]  STATUS     show what is running
echo.
echo    [5]  DASHBOARD  open in browser
echo    [6]  VAULT      open notes folder
echo    [7]  LIBRARY    open PDF folder
echo    [8]  LOGS       open logs folder
echo.
echo    [9]  REINDEX    rebuild RAG index for PDFs
echo    [0]  DISTILL    distill 5 latest transcripts
echo.
echo    [B]  BACKUP     create ZIP
echo    [S]  SHORTCUT   create desktop shortcut
echo    [Q]  QUIT       leave menu (services keep running)
echo  ====================================================
echo.
set "choice="
set /p choice="  Choice: "

if /i "%choice%"=="1" goto do_start
if /i "%choice%"=="2" goto do_stop
if /i "%choice%"=="3" goto do_restart
if /i "%choice%"=="4" goto status_full
if /i "%choice%"=="5" goto dashboard
if /i "%choice%"=="6" goto vault
if /i "%choice%"=="7" goto library
if /i "%choice%"=="8" goto logs
if /i "%choice%"=="9" goto reindex
if /i "%choice%"=="0" goto distill
if /i "%choice%"=="B" goto backup
if /i "%choice%"=="S" goto shortcut
if /i "%choice%"=="Q" goto end
goto menu

:status_line
set "oll=stopped"
set "dash=stopped"
powershell.exe -NoProfile -Command "if (Get-Process ollama -ErrorAction SilentlyContinue) { exit 1 }" >nul 2>&1
if errorlevel 1 set "oll=RUNNING"
powershell.exe -NoProfile -Command "try { Invoke-WebRequest 'http://127.0.0.1:7860/api/status' -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 1 } catch { exit 0 }" >nul 2>&1
if errorlevel 1 set "dash=RUNNING"
echo    Ollama    : !oll!
echo    Dashboard : !dash!
exit /b 0

:do_start
echo.
echo  Launching...
call "%~dp0start.cmd"
echo.
timeout /t 3 >nul
goto menu

:do_stop
echo.
echo  Stopping...
call "%~dp0stop.cmd"
timeout /t 2 >nul
goto menu

:do_restart
echo.
echo  Restarting...
call "%~dp0stop.cmd"
timeout /t 2 >nul
call "%~dp0start.cmd"
timeout /t 3 >nul
goto menu

:status_full
echo.
echo  ---- STATUS ----
powershell.exe -NoProfile -Command "try { $s = (Invoke-WebRequest 'http://127.0.0.1:7860/api/status' -UseBasicParsing -TimeoutSec 3).Content | ConvertFrom-Json; Write-Host ('   Ollama models : ' + $s.ollama.count); Write-Host ('   GPU           : ' + $s.gpu.name + '  VRAM ' + $s.gpu.vram_used_mb + '/' + $s.gpu.vram_total_mb + ' MB'); Write-Host ('   Vault notes   : ' + $s.vault.notes); Write-Host ('   Library PDFs  : ' + $s.library.pdfs); Write-Host ('   Uptime        : ' + $s.system.uptime_sec + 's') } catch { Write-Host '   Dashboard not responding' }"
echo.
pause
goto menu

:dashboard
start "" "http://127.0.0.1:7860"
goto menu

:vault
if not exist "%~dp0data\vault" mkdir "%~dp0data\vault"
start "" "%~dp0data\vault"
goto menu

:library
if not exist "%~dp0data\library" mkdir "%~dp0data\library"
start "" "%~dp0data\library"
goto menu

:logs
if not exist "%~dp0logs" mkdir "%~dp0logs"
start "" "%~dp0logs"
goto menu

:reindex
echo.
echo  Triggering RAG reindex...
powershell.exe -NoProfile -Command "try { $r = Invoke-WebRequest 'http://127.0.0.1:7860/api/library/reindex' -Method POST -UseBasicParsing; Write-Host ('  ' + $r.Content) } catch { Write-Host '  Dashboard not responding - start it first via [1]' }"
echo.
pause
goto menu

:distill
echo.
echo  Distilling last 5 transcripts via qwen2.5:14b...
powershell.exe -NoProfile -Command "try { $body = '{\"mode\":\"run\",\"model\":\"qwen2.5:14b\",\"limit\":5}'; $r = Invoke-WebRequest 'http://127.0.0.1:7860/api/transcripts/run' -Method POST -ContentType 'application/json' -Body $body -UseBasicParsing; Write-Host ('  ' + $r.Content) } catch { Write-Host '  Dashboard not responding' }"
echo.
pause
goto menu

:backup
echo.
echo  Creating backup...
powershell.exe -NoProfile -Command "try { $body = '{\"include_keys\":false,\"include_distilled\":true}'; $r = Invoke-WebRequest 'http://127.0.0.1:7860/api/backup' -Method POST -ContentType 'application/json' -Body $body -UseBasicParsing; $j = $r.Content | ConvertFrom-Json; Write-Host ('  Backup: ' + $j.name + '  ' + $j.size_mb + ' MB  ' + $j.files + ' files') } catch { Write-Host '  Dashboard not responding' }"
echo.
pause
goto menu

:shortcut
echo.
echo  Creating Brain shortcuts on Desktop and Start Menu...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0make-shortcut.ps1" -StartMenu
echo.
pause
goto menu

:end
endlocal
exit /b 0
