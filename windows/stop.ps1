#Requires -Version 5.1
$Root = Split-Path $PSScriptRoot -Parent
$script:BrainRoot = $Root
. (Join-Path $PSScriptRoot "Locale.ps1")

try {
    Invoke-WebRequest "http://127.0.0.1:7860/api/shutdown" -Method POST -UseBasicParsing -TimeoutSec 3 | Out-Null
    Write-Host (L stop_graceful) -ForegroundColor DarkGray
    Start-Sleep -Milliseconds 800
} catch { }

foreach ($name in @("ollama", "dashboard", "tray")) {
    $pidFile = Join-Path $Root "logs\$name.pid"
    if (Test-Path $pidFile) {
        $procId = Get-Content $pidFile
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host (L stop_pid $name $procId) -ForegroundColor Green
        } catch {
            Write-Host (L stop_pid_gone $name $procId) -ForegroundColor DarkGray
        }
        Remove-Item $pidFile -ErrorAction SilentlyContinue
    }
}

Get-Process ollama -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process ollama_llama_server -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

$brainPython = (Join-Path $Root "bin\python\python.exe").ToLower()
$brainPythonw = (Join-Path $Root "bin\python\pythonw.exe").ToLower()
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue | ForEach-Object {
    $exe = if ($_.ExecutablePath) { $_.ExecutablePath.ToLower() } else { "" }
    if ($exe -eq $brainPython -or $exe -eq $brainPythonw) {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            Write-Host (L stop_stray $_.Name $_.ProcessId) -ForegroundColor Yellow
        } catch { }
    }
}

Write-Host (L stop_done) -ForegroundColor Cyan
