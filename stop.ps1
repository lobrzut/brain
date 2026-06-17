# Backward-compatible wrapper — use windows\stop.ps1 or Stop.bat
$Root = $PSScriptRoot
& (Join-Path $Root "windows\stop.ps1") @args
