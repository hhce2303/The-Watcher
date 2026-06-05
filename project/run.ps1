# The Watcher launcher — DEV MODE
# Siempre arranca desde cero: borra user_config y requests para que
# aparezca el wizard de selección de rol en cada ejecución.
# Usage: .\run.ps1

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

if (-not (Test-Path ".\venv\Scripts\Activate.ps1")) {
    Write-Error "Virtual environment not found. Run: python -m venv venv && pip install -r requirements.txt"
    exit 1
}

.\venv\Scripts\Activate.ps1

# ── Reset de estado: forzar flujo de instalación/rol ─────────────────────────
$configDir = "$env:LOCALAPPDATA\The Watcher"
$userConfig = "$configDir\user_config.json"
$requestsDir = "$configDir\requests"

if (Test-Path $userConfig) {
    Remove-Item -Force $userConfig
    Write-Host "[reset] user_config.json eliminado → el wizard de rol aparecerá al iniciar."
}

if (Test-Path $requestsDir) {
    Remove-Item -Recurse -Force $requestsDir
    Write-Host "[reset] Carpeta requests/ eliminada."
}

Write-Host "[reset] Listo. Arrancando desde la selección de rol..." -ForegroundColor Cyan

# ── Qt Quick Controls style ───────────────────────────────────────────────────
# Force the "Basic" style so custom `background` properties on TextField,
# ComboBox, etc. are respected.  The default native Windows style ignores them
# and emits QML warnings.
$env:QT_QUICK_CONTROLS_STYLE = "Basic"

# ── Qt plugin paths ───────────────────────────────────────────────────────────
$pyside6PluginsPath = & .\venv\Scripts\python.exe -c `
    "import PySide6, pathlib; print(pathlib.Path(PySide6.__file__).parent / 'plugins')" `
    2>$null
if ($pyside6PluginsPath) {
    $env:QT_PLUGIN_PATH = $pyside6PluginsPath
    Write-Host "Qt plugin path: $env:QT_PLUGIN_PATH"
}

$pyside6QmlPath = & .\venv\Scripts\python.exe -c `
    "import PySide6, pathlib; print(pathlib.Path(PySide6.__file__).parent / 'qml')" `
    2>$null
if ($pyside6QmlPath) {
    $env:QML2_IMPORT_PATH = $pyside6QmlPath
    Write-Host "QML import path: $env:QML2_IMPORT_PATH"
}

python -m app.main
