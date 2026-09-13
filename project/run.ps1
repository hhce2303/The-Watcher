# The Watcher launcher - DEV MODE
# QML/PySide6 are gone (F3): the UI is Tauri + React, connecting to the Python
# backend over the named pipe. This script starts the backend headless (role-
# aware: --daemon for Operator, --sidecar otherwise) and, by default, the
# Tauri dev shell alongside it.
#
# Usage:
#   .\run.ps1                  # Tauri dev: role-aware Python backend + `npm run tauri dev` (default)
#   .\run.ps1 -Mode daemon     # headless Operator daemon only, no UI (ADR-0010)
#   .\run.ps1 -Mode sidecar    # headless IT/Supervisor sidecar only, no UI (stdin shutdown)
#   .\run.ps1 -ResetRole       # wipe the persisted role first, so the wizard reappears
param(
    [ValidateSet("tauri", "daemon", "sidecar")]
    [string]$Mode = "tauri",
    [switch]$ResetRole
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

# El venv vive FUERA de OneDrive (en %LOCALAPPDATA%) para no sincronizarse entre PCs.
$venvDir = Join-Path $env:LOCALAPPDATA "The Watcher\venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    $setup = Join-Path $scriptDir "..\setup_env.ps1"
    if (Test-Path $setup) {
        Write-Host "Entorno virtual no encontrado -> ejecutando setup_env.ps1..." -ForegroundColor Yellow
        & powershell -ExecutionPolicy Bypass -File $setup
    }
    if (-not (Test-Path $venvPython)) {
        Write-Error "No se pudo preparar el entorno virtual. Ejecuta setup_env.ps1 manualmente."
        exit 1
    }
}

# -- Reset opcional: forzar el wizard de rol (-ResetRole) ----------------------
$configDir = "$env:LOCALAPPDATA\The Watcher"
$userConfig = "$configDir\user_config.json"
$requestsDir = "$configDir\requests"

if ($ResetRole) {
    if (Test-Path $userConfig) {
        Remove-Item -Force $userConfig
        Write-Host "[reset] user_config.json eliminado -> el wizard de rol aparecera al iniciar." -ForegroundColor Cyan
    }
    if (Test-Path $requestsDir) {
        Remove-Item -Recurse -Force $requestsDir
        Write-Host "[reset] Carpeta requests/ eliminada." -ForegroundColor Cyan
    }
}

# -- Rol persistido (para decidir --daemon vs --sidecar) -----------------------
function Get-PersistedRole {
    if (Test-Path $userConfig) {
        try {
            $cfg = Get-Content $userConfig -Raw | ConvertFrom-Json
            if ($cfg.role) { return $cfg.role }
        } catch {
            Write-Warning "No se pudo leer user_config.json - asumiendo rol sin configurar."
        }
    }
    return ""
}

$role = Get-PersistedRole
$backendFlag = if ($role -eq "operator") { "--daemon" } else { "--sidecar" }

# -- Launch by mode (ADR-0010; C4 - the backend picks --daemon/--sidecar) -----
switch ($Mode) {
    "daemon"  { Write-Host "Launching headless DAEMON (Operator topology)..." -ForegroundColor Cyan
                & $venvPython -m app.main --daemon }
    "sidecar" { Write-Host "Launching headless SIDECAR (IT/Supervisor topology)..." -ForegroundColor Cyan
                & $venvPython -m app.main --sidecar }
    "tauri"   {
        Write-Host "Launching TAURI dev mode: Python backend ($backendFlag, role='$role') + Tauri shell..." -ForegroundColor Cyan
        # Build artefacts must live outside OneDrive (TD: sync-lock permissions).
        $env:CARGO_TARGET_DIR = "$env:LOCALAPPDATA\the-watcher\target"
        # Start the Python backend in the background; it binds the named pipe.
        $backend = Start-Process $venvPython -ArgumentList "-m", "app.main", $backendFlag `
            -PassThru -NoNewWindow
        Write-Host "  Python backend PID: $($backend.Id)" -ForegroundColor DarkGray
        # Give the backend a moment to bind the pipe before Tauri connects.
        Start-Sleep -Seconds 1
        # Launch Tauri dev (blocks; Ctrl-C will kill both).
        try {
            Set-Location (Split-Path -Parent $scriptDir)
            npm run tauri -- dev
        } finally {
            Write-Host "Stopping Python backend..." -ForegroundColor Yellow
            # send shutdown via stdin before kill (TD-3: process.kill() misses PyInstaller children).
            if (-not $backend.HasExited) {
                $backend.Kill()
            }
        }
    }
}
