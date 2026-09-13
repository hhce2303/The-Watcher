<#
.SYNOPSIS
    Starts The Watcher backend and, by default, its Tauri development UI.

.DESCRIPTION
    The backend topology follows the persisted machine role:
      operator              -> detached --daemon (continues when the UI exits)
      it / supervisor / ""  -> --sidecar (receives a graceful stdin shutdown
                              once the development UI exits)

    The Tauri shell does not package or launch Python yet (`externalBin` is
    intentionally empty), so this is the root launcher for the complete local
    development topology. It uses the uv-managed venv outside OneDrive at
    %LOCALAPPDATA%\The Watcher\venv. If the environment is missing or broken,
    it invokes setup_env.ps1 to repair it automatically.

.EXAMPLE
    .\Start-TheWatcher.ps1

.EXAMPLE
    .\Start-TheWatcher.ps1 -BackendMode Daemon

.EXAMPLE
    .\Start-TheWatcher.ps1 -BackendMode Sidecar -NoUi

.EXAMPLE
    .\Start-TheWatcher.ps1 -Bootstrap
    # Forces a uv dependency installation/repair before starting.

.EXAMPLE
    .\Start-TheWatcher.ps1 -EnrollBrowserLocal
    # Prints the device ID and public key to register in SIGDailyReport.

.EXAMPLE
    .\Start-TheWatcher.ps1 -SetupBrowserLocalTls
    # Creates the mkcert certificate needed by the browser-local iframe.
#>

[CmdletBinding()]
param(
    [ValidateSet("Auto", "Daemon", "Sidecar")]
    [string]$BackendMode = "Auto",
    [switch]$NoUi,
    [switch]$Bootstrap,
    [switch]$EnrollBrowserLocal,
    [switch]$SetupBrowserLocalTls
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoDir = $PSScriptRoot
$projectDir = Join-Path $repoDir "project"
$venvPython = Join-Path $env:LOCALAPPDATA "The Watcher\venv\Scripts\python.exe"
$setupScript = Join-Path $repoDir "setup_env.ps1"
$browserTlsSetupScript = Join-Path $repoDir "setup_browser_local_tls.ps1"
$userConfig = Join-Path $env:LOCALAPPDATA "The Watcher\user_config.json"
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"

# rustup normally updates PATH for future shells only.  Make the Tauri command
# work in a freshly opened PowerShell too, without requiring a logoff/reboot.
if ((Test-Path -LiteralPath (Join-Path $cargoBin "cargo.exe")) -and ($env:Path -notlike "*$cargoBin*")) {
    $env:Path = "$cargoBin;$env:Path"
}

function Get-PersistedRole {
    if (-not (Test-Path -LiteralPath $userConfig)) {
        return ""
    }

    try {
        $config = Get-Content -LiteralPath $userConfig -Raw -Encoding utf8 | ConvertFrom-Json
        if ($null -ne $config.role) {
            return [string]$config.role
        }
    }
    catch {
        Write-Warning "No se pudo leer user_config.json; se usará el modo sidecar seguro."
    }

    return ""
}

function Test-VenvHealthy {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        return $false
    }

    try {
        & $venvPython --version *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

if ($Bootstrap -or -not (Test-VenvHealthy)) {
    if (-not (Test-Path -LiteralPath $setupScript)) {
        throw "No se encontró '$setupScript'."
    }

    Write-Host "Preparando/reparando el entorno Python con uv..." -ForegroundColor Cyan
    & $setupScript
    if ($LASTEXITCODE -ne 0 -or -not (Test-VenvHealthy)) {
        throw "setup_env.ps1 no dejó un venv saludable en '$venvPython'."
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $projectDir "app\main.py"))) {
    throw "No se encontró el backend en '$projectDir\app\main.py'."
}

if ($SetupBrowserLocalTls) {
    if (-not (Test-Path -LiteralPath $browserTlsSetupScript)) {
        throw "No se encontró '$browserTlsSetupScript'."
    }
    & $browserTlsSetupScript
    exit $LASTEXITCODE
}

if ($EnrollBrowserLocal) {
    Write-Host "Generando/leyendo identidad de enrolamiento browser-local..." -ForegroundColor Cyan
    Push-Location $projectDir
    try {
        & $venvPython -m app.tools.browser_local_enroll
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

$role = Get-PersistedRole
switch ($BackendMode) {
    "Daemon"  { $backendFlag = "--daemon" }
    "Sidecar" { $backendFlag = "--sidecar" }
    default {
        $backendFlag = if ($role -eq "operator") { "--daemon" } else { "--sidecar" }
    }
}

if ($NoUi) {
    Write-Host "Iniciando backend headless ($backendFlag; role='$role')..." -ForegroundColor Cyan
    Push-Location $projectDir
    try {
        & $venvPython -m app.main $backendFlag
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($null -eq $npm) {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
}
if ($null -eq $npm) {
    throw "No se encontró npm. Instala Node.js 22+ y ejecuta npm install en la raíz del repositorio."
}

$nodeModules = Join-Path $repoDir "node_modules"
if (-not (Test-Path -LiteralPath $nodeModules)) {
    throw "No existe node_modules. Ejecuta 'npm install' en '$repoDir' antes de iniciar la UI."
}

$backendInfo = New-Object System.Diagnostics.ProcessStartInfo
$backendInfo.FileName = $venvPython
$backendInfo.Arguments = "-m app.main $backendFlag"
$backendInfo.WorkingDirectory = $projectDir
$backendInfo.UseShellExecute = $false
$backendInfo.RedirectStandardInput = $true
$backendInfo.CreateNoWindow = $false

$backend = New-Object System.Diagnostics.Process
$backend.StartInfo = $backendInfo

Write-Host "Iniciando backend ($backendFlag; role='$role')..." -ForegroundColor Cyan
if (-not $backend.Start()) {
    throw "No se pudo iniciar el backend Python."
}
Write-Host "  Backend PID: $($backend.Id)" -ForegroundColor DarkGray

# The Tauri client has an automatic reconnect loop, so it is safe to launch
# immediately while the backend is binding its named pipe.
$uiExitCode = 1
try {
    Push-Location $repoDir
    try {
        Write-Host "Iniciando Tauri + React..." -ForegroundColor Cyan
        & $npm.Source run tauri -- dev
        $uiExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($backendFlag -eq "--sidecar" -and -not $backend.HasExited) {
        Write-Host "Solicitando apagado limpio del sidecar..." -ForegroundColor Yellow
        try {
            $backend.StandardInput.WriteLine("shutdown")
            $backend.StandardInput.Flush()
            if (-not $backend.WaitForExit(10000)) {
                Write-Warning "El sidecar no confirmó el apagado en 10 s; revisa el log antes de reiniciarlo."
            }
        }
        catch {
            Write-Warning "No se pudo enviar shutdown al sidecar: $($_.Exception.Message)"
        }
    }
    elseif ($backendFlag -eq "--daemon" -and -not $backend.HasExited) {
        Write-Host "El daemon sigue activo (PID $($backend.Id)); es el comportamiento esperado para Operator." -ForegroundColor Green
    }
}

exit $uiExitCode
