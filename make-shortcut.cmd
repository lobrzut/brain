@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0make-shortcut.ps1" %*
pause
