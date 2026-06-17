#Requires -Version 5.1
<#
.SYNOPSIS
  Brain — Windows portable edition installer.
.DESCRIPTION
  Downloads embedded Python + Ollama, installs pip deps, creates data dirs and config.json.
  Source code (dashboard/, pipeline/) must already be in the repo folder.
.PARAMETER Root
  Install root. Default: parent of windows/ (repo root).
.PARAMETER Model
  Initial Ollama model to pull.
#>
[CmdletBinding()]
param(
    [string]$Root = $(Split-Path $PSScriptRoot -Parent),
    [string]$Model = "qwen2.5:14b",
    [int]$DashboardPort = 7860,
    [int]$OllamaPort = 11434,
    [switch]$SkipModelPull,
    [switch]$SkipPython
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$script:BrainRoot = $Root
. (Join-Path $PSScriptRoot "Locale.ps1")

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host " OK $msg" -ForegroundColor Green }

if (-not (Test-Path (Join-Path $Root "dashboard\app.py"))) {
    Write-Host (L install_missing_git) -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host (L install_title) -ForegroundColor Magenta
Write-Host "    Root: $Root"
Write-Host ""

$P = [ordered]@{
    Root   = $Root
    Bin    = Join-Path $Root "bin"
    Python = Join-Path $Root "bin\python"
    Ollama = Join-Path $Root "bin\ollama"
    Data   = Join-Path $Root "data"
    Logs   = Join-Path $Root "logs"
    Models = Join-Path $Root "data\ollama-models"
}

foreach ($d in @($P.Bin, $P.Python, $P.Ollama, $P.Data, $P.Logs,
    (Join-Path $P.Data "vault"), (Join-Path $P.Data "library"),
    (Join-Path $P.Data "backups"))) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

# Seed example files if missing
$keysExample = Join-Path $P.Data "api-keys.example.json"
$keysFile = Join-Path $P.Data "api-keys.json"
if ((Test-Path $keysExample) -and -not (Test-Path $keysFile)) {
    Copy-Item $keysExample $keysFile
}
$userExample = Join-Path $P.Data "vault\USER.example.md"
$userFile = Join-Path $P.Data "vault\USER.md"
if ((Test-Path $userExample) -and -not (Test-Path $userFile)) {
    Copy-Item $userExample $userFile
}

if (-not $SkipPython) {
    Write-Step (L install_python)
    $pyExe = Join-Path $P.Python "python.exe"
    if (Test-Path $pyExe) {
        Write-Ok (L install_already) $pyExe
    } else {
        $pyUrl = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip"
        $pyZip = Join-Path $env:TEMP "brain-python-embed.zip"
        Invoke-WebRequest -Uri $pyUrl -OutFile $pyZip
        Expand-Archive -Path $pyZip -DestinationPath $P.Python -Force
        Remove-Item $pyZip -Force -ErrorAction SilentlyContinue
        $pth = Get-ChildItem $P.Python -Filter "python3*._pth" | Select-Object -First 1
        if ($pth) {
            (Get-Content $pth.FullName) -replace '^#\s*import site', 'import site' | Set-Content $pth.FullName -Encoding ASCII
        }
        $getPip = Join-Path $env:TEMP "get-pip.py"
        Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip
        & $pyExe $getPip --no-warn-script-location
        Remove-Item $getPip -Force -ErrorAction SilentlyContinue
        Write-Ok "Python"
    }

    Write-Step (L install_deps)
    $req = Join-Path $Root "requirements.txt"
    & $pyExe -m pip install --upgrade pip --quiet
    & $pyExe -m pip install --quiet -r $req
    Write-Ok "pip"
}

Write-Step (L install_ollama)
$ollamaExe = Join-Path $P.Ollama "ollama.exe"
if (Test-Path $ollamaExe) {
    Write-Ok (L install_already)
} else {
    $url = "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip"
    $zip = Join-Path $env:TEMP "brain-ollama.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $P.Ollama -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path $ollamaExe)) {
        $found = Get-ChildItem $P.Ollama -Recurse -Filter "ollama.exe" | Select-Object -First 1
        if ($found) { Move-Item $found.FullName $ollamaExe -Force }
    }
    Write-Ok "Ollama"
}

Write-Step (L install_config)
$cfgPath = Join-Path $Root "config.json"
if (-not (Test-Path $cfgPath)) {
    $example = Join-Path $Root "config.example.json"
    if (Test-Path $example) {
        $json = Get-Content $example -Raw | ConvertFrom-Json
        $json.root = $Root
        $json.edition = "windows"
        $json | ConvertTo-Json -Depth 6 | Set-Content $cfgPath -Encoding UTF8
    } else {
        [ordered]@{
            version = "0.5.0"; edition = "windows"; root = $Root
            ollama_port = $OllamaPort; dashboard_port = $DashboardPort
            default_model = $Model
        } | ConvertTo-Json -Depth 4 | Set-Content $cfgPath -Encoding UTF8
    }
}
Write-Ok "config.json"

# Ollama portable env (used by tray on Windows)
$ollamaEnvDir = Join-Path $Root "ollama-models"
New-Item -ItemType Directory -Force -Path $ollamaEnvDir | Out-Null
$envBat = Join-Path $ollamaEnvDir "env.bat"
@"
@echo off
set OLLAMA_MODELS=%~dp0..\data\ollama-models
set OLLAMA_HOST=127.0.0.1:$OllamaPort
"@ | Set-Content $envBat -Encoding ASCII

if (-not $SkipModelPull) {
    Write-Step "ollama pull $Model"
    $env:OLLAMA_MODELS = $P.Models
    $env:OLLAMA_HOST = "127.0.0.1:$OllamaPort"
    & $ollamaExe pull $Model 2>&1 | Out-Host
    & $ollamaExe pull nomic-embed-text 2>&1 | Out-Host
}

Write-Host ""
Write-Host (L install_done) -ForegroundColor Green
Write-Host ""
