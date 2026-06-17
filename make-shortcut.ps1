# make-shortcut.ps1
# Creates two Windows shortcuts:
#   "Brain"      -> launch.cmd  (one-click: starts everything + opens dashboard)
#   "Brain Menu" -> brain.bat   (advanced menu)
# Both placed on Desktop. Optionally also in Start Menu.

param(
    [switch]$StartMenu,
    [switch]$NoMenu      # if set: only create the simple launcher, no "Brain Menu"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Icon = Join-Path $Root "brain.ico"

if (-not (Test-Path $Icon)) {
    Write-Host "[!] brain.ico missing - generating now..." -ForegroundColor Yellow
    $pyExe = Join-Path $Root "bin\python\python.exe"
    $makeIcon = Join-Path $Root "pipeline\make_icon.py"
    if ((Test-Path $pyExe) -and (Test-Path $makeIcon)) {
        & $pyExe $makeIcon
    } else {
        Write-Host "[ERR] cannot generate icon" -ForegroundColor Red
        exit 1
    }
}

$WshShell = New-Object -ComObject WScript.Shell
$desktop  = [Environment]::GetFolderPath("Desktop")
$smFolder = [Environment]::GetFolderPath("StartMenu")
$programs = Join-Path $smFolder "Programs"

function Write-Shortcut {
    param(
        [string]$Folder,
        [string]$Label,
        [string]$Target,
        [string]$Description
    )
    if (-not (Test-Path $Folder)) { return }
    $lnk = Join-Path $Folder "$Label.lnk"
    $sc = $WshShell.CreateShortcut($lnk)
    $sc.TargetPath       = $Target
    $sc.WorkingDirectory = $Root
    $sc.IconLocation     = "$Icon,0"
    $sc.Description      = $Description
    $sc.WindowStyle      = 1   # 1 = normal, 7 = minimized
    $sc.Save()
    Write-Host "[ok] $Label  ->  $lnk" -ForegroundColor Green
}

$launchTarget = Join-Path $Root "launch.cmd"
$menuTarget   = Join-Path $Root "brain.bat"

# Main shortcut: ONE-CLICK launch
Write-Shortcut -Folder $desktop -Label "Brain" -Target $launchTarget `
    -Description "Brain AI Hub - one-click launcher (starts services + opens dashboard)"

if (-not $NoMenu.IsPresent) {
    Write-Shortcut -Folder $desktop -Label "Brain Menu" -Target $menuTarget `
        -Description "Brain AI Hub - advanced menu (start/stop/backup/distill/...)"
}

if ($StartMenu.IsPresent) {
    Write-Shortcut -Folder $programs -Label "Brain" -Target $launchTarget `
        -Description "Brain AI Hub - one-click launcher"
    if (-not $NoMenu.IsPresent) {
        Write-Shortcut -Folder $programs -Label "Brain Menu" -Target $menuTarget `
            -Description "Brain AI Hub - advanced menu"
    }
}

Write-Host ""
Write-Host "Gotowe. Na pulpicie:" -ForegroundColor Cyan
Write-Host "  - kliknij 'Brain' aby uruchomic apke (jeden klik, otwiera dashboard)"
if (-not $NoMenu.IsPresent) {
    Write-Host "  - kliknij 'Brain Menu' aby otworzyc zaawansowane menu"
}
