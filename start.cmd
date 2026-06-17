@echo off
REM Wrapper for start.ps1 - bypasses ExecutionPolicy without changing system settings.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
