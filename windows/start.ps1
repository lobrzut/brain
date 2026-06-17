#Requires -Version 5.1
# Brain Windows — start (tray owns Ollama + dashboard lifecycle)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$script:BrainRoot = $Root
. (Join-Path $PSScriptRoot "Locale.ps1")

$pyw    = Join-Path $Root "bin\python\pythonw.exe"
$trayPy = Join-Path $Root "dashboard\tray.py"

if (-not (Test-Path $pyw)) {
    Write-Host (L start_missing_python $pyw) -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $trayPy)) {
    Write-Host "Missing $trayPy" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null

$existing = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'tray\.py' }
if ($existing) {
    Write-Host (L start_tray_running $existing.ProcessId) -ForegroundColor Yellow
    Start-Process "http://127.0.0.1:7860"
    exit 0
}

$trayProc = Start-Process -FilePath $pyw -ArgumentList @($trayPy) `
    -WorkingDirectory (Join-Path $Root "dashboard") `
    -WindowStyle Hidden -PassThru
Set-Content (Join-Path $Root "logs\tray.pid") $trayProc.Id
Write-Host (L start_tray_started $trayProc.Id) -ForegroundColor Green

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:7860/api/status" -TimeoutSec 2 -UseBasicParsing
        if ($r.StatusCode -eq 200) { break }
    } catch { Start-Sleep -Milliseconds 800 }
}

Start-Process "http://127.0.0.1:7860"
Write-Host ""
Write-Host "  $(L start_dashboard)" -ForegroundColor Cyan
Write-Host "  $(L start_ollama)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  $(L start_hint_stop)" -ForegroundColor DarkGray
