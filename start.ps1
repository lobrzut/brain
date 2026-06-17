# Backward-compatible wrapper — use windows\start.ps1 or Start.bat
$Root = $PSScriptRoot
& (Join-Path $Root "windows\start.ps1") @args
