#Requires -Version 5.1
# Shared PL/EN strings for Brain Windows scripts.
if (Get-Command Get-BrainLocale -ErrorAction SilentlyContinue) { return }

function Get-BrainLocaleEnvPath {
    $root = if ($script:BrainRoot) { $script:BrainRoot } else { Split-Path $PSScriptRoot -Parent }
    return Join-Path $root 'locale.env'
}

function Get-BrainLocale {
    $path = Get-BrainLocaleEnvPath
    if (Test-Path -LiteralPath $path) {
        $line = Get-Content -LiteralPath $path -TotalCount 1 -ErrorAction SilentlyContinue
        if ($line -match '^\s*LANG\s*=\s*(pl|en)\s*$') { return $Matches[1] }
    }
    try {
        $ui = [System.Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName
        if ($ui -eq 'en') { return 'en' }
    } catch { }
    return 'pl'
}

function Set-BrainLocale([ValidateSet('pl', 'en')][string]$Lang) {
    $path = Get-BrainLocaleEnvPath
    $dir = Split-Path $path -Parent
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    "LANG=$Lang" | Set-Content -LiteralPath $path -Encoding UTF8 -NoNewline
}

$script:BrainLocaleStrings = @{
    pl = @{
        install_title           = 'Brain - instalacja (Windows portable)'
        install_python          = 'Instalacja Python 3.12 (embedded)...'
        install_deps            = 'Instalacja zaleznosci Python...'
        install_ollama          = 'Instalacja Ollama...'
        install_config          = 'Zapis config.json...'
        install_done            = 'Gotowe. Uruchom Start.bat lub .\start.ps1'
        install_already         = 'Juz zainstalowane:'
        install_missing_git     = 'Brak kodu Brain. Sklonuj repozytorium lub uruchom z katalogu brain/.'
        start_tray_running      = 'Tray juz dziala (PID {0}). Otwieram http://127.0.0.1:7860'
        start_tray_started      = 'Brain tray uruchomiony (PID {0})'
        start_dashboard         = 'Dashboard: http://127.0.0.1:7860'
        start_ollama            = 'Ollama:    http://127.0.0.1:11434'
        start_hint_stop         = 'Stop: tray -> QUIT BRAIN lub .\stop.ps1'
        start_missing_python    = 'Brak {0} - uruchom Install.bat lub windows\install.ps1'
        stop_graceful           = 'Wyslano graceful shutdown do dashboardu'
        stop_pid                = 'Zatrzymano {0} (PID {1})'
        stop_pid_gone           = 'Proces {0} (PID {1}) nie dziala'
        stop_stray              = 'Zatrzymano osierocony {0} (PID {1})'
        stop_done               = 'Zatrzymano.'
    }
    en = @{
        install_title           = 'Brain - install (Windows portable)'
        install_python          = 'Installing Python 3.12 (embedded)...'
        install_deps            = 'Installing Python dependencies...'
        install_ollama          = 'Installing Ollama...'
        install_config          = 'Writing config.json...'
        install_done            = 'Done. Run Start.bat or .\start.ps1'
        install_already         = 'Already present:'
        install_missing_git     = 'Brain source missing. Clone the repo or run from brain/ folder.'
        start_tray_running      = 'Tray already running (PID {0}). Opening http://127.0.0.1:7860'
        start_tray_started      = 'Brain tray started (PID {0})'
        start_dashboard         = 'Dashboard: http://127.0.0.1:7860'
        start_ollama            = 'Ollama:    http://127.0.0.1:11434'
        start_hint_stop         = 'Stop: tray -> QUIT BRAIN or .\stop.ps1'
        start_missing_python    = 'Missing {0} - run Install.bat or windows\install.ps1'
        stop_graceful           = 'Sent graceful shutdown to dashboard'
        stop_pid                = 'Stopped {0} (PID {1})'
        stop_pid_gone           = 'Process {0} (PID {1}) not running'
        stop_stray              = 'Stopped stray {0} (PID {1})'
        stop_done               = 'Done.'
    }
}

function L([string]$Key, [object[]]$FormatArgs = @()) {
    $lang = Get-BrainLocale
    $table = $script:BrainLocaleStrings[$lang]
    if (-not $table.ContainsKey($Key)) { $table = $script:BrainLocaleStrings['en'] }
    $fmt = $table[$Key]
    if ($null -eq $fmt) { return $Key }
    if ($FormatArgs.Count -gt 0) { return [string]::Format($fmt, $FormatArgs) }
    return $fmt
}
