<#
.SYNOPSIS
    Provisions The Watcher's per-machine Python environment with uv.

.DESCRIPTION
    The venv remains outside OneDrive at %LOCALAPPDATA%\The Watcher\venv.
    uv owns Python discovery/install (3.13) and dependency synchronization from
    project\requirements.txt, so a missing or broken system `python` on PATH is
    no longer a prerequisite.

    The Rust segment engine is optional. A failed native build leaves the
    FFmpeg fallback available and does not fail setup.
#>

[CmdletBinding()]
param(
    [switch]$Recreate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoDir = $PSScriptRoot
$venvPath = Join-Path $env:LOCALAPPDATA "The Watcher\venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$requirements = Join-Path $repoDir "project\requirements.txt"
$crateDir = Join-Path $repoDir "project\native\watcher_segments"

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) {
    throw "No se encontró uv. Instálalo con: winget install --id=astral-sh.uv -e"
}
if (-not (Test-Path -LiteralPath $requirements)) {
    throw "No se encontró '$requirements'."
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

Write-Host "uv: $(& $uv.Source --version)" -ForegroundColor Cyan
Write-Host "Asegurando Python 3.13 mediante uv..." -ForegroundColor Cyan
& $uv.Source python install 3.13
if ($LASTEXITCODE -ne 0) {
    throw "uv no pudo instalar o localizar Python 3.13."
}

$healthy = Test-VenvHealthy
if ($Recreate -or -not $healthy) {
    $venvArgs = @("venv", "--python", "3.13")
    if (Test-Path -LiteralPath $venvPath) {
        $venvArgs += "--clear"
    }
    $venvArgs += $venvPath

    Write-Host "Creando/reparando venv con uv en '$venvPath'..." -ForegroundColor Cyan
    & $uv.Source @venvArgs
    if ($LASTEXITCODE -ne 0 -or -not (Test-VenvHealthy)) {
        throw "uv no pudo crear un venv saludable en '$venvPath'."
    }
}
else {
    Write-Host "Venv existente válido: $venvPython" -ForegroundColor DarkGray
}

# requirements.txt is an input manifest, not a fully compiled lockfile (for
# example, it does not enumerate every transitive onnxruntime dependency).
# `uv pip install -r` resolves that complete graph. `uv pip sync` would treat
# this file as a final package list and leave required transitive packages out.
Write-Host "Sincronizando project\\requirements.txt con uv..." -ForegroundColor Cyan
& $uv.Source pip install --python $venvPython -r $requirements
if ($LASTEXITCODE -ne 0) {
    throw "uv no pudo instalar '$requirements'."
}

# Native Rust engine — optional. Use uv for maturin/wheel installation too, so
# this script never falls back to a globally installed pip.
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if ((Test-Path -LiteralPath (Join-Path $cargoBin "cargo.exe")) -and ($env:Path -notlike "*$cargoBin*")) {
    # rustup adds this for new shells, but provisioning often runs immediately
    # after installation in the same PowerShell session.
    $env:Path = "$cargoBin;$env:Path"
}
$cargo = Get-Command cargo -ErrorAction SilentlyContinue
if ($null -eq $cargo -or -not (Test-Path -LiteralPath $crateDir)) {
    Write-Host "Rust/cargo no disponible; se usará el fallback FFmpeg para segmentos." -ForegroundColor Yellow
}
else {
    Write-Host "Compilando el motor nativo Rust (opcional)..." -ForegroundColor Cyan
    try {
        & $uv.Source pip install --python $venvPython maturin
        if ($LASTEXITCODE -ne 0) {
            throw "uv no pudo instalar maturin."
        }

        $wheelDir = Join-Path $env:TEMP "the-watcher-wheels"
        New-Item -ItemType Directory -Force -Path $wheelDir | Out-Null
        Push-Location $crateDir
        try {
            & $venvPython -m maturin build --release --interpreter $venvPython --out $wheelDir
            if ($LASTEXITCODE -ne 0) {
                throw "maturin no pudo compilar watcher_segments."
            }
        }
        finally {
            Pop-Location
        }

        $wheel = Get-ChildItem -LiteralPath $wheelDir -Filter "watcher_segments-*.whl" |
            Sort-Object LastWriteTime | Select-Object -Last 1
        if ($null -eq $wheel) {
            throw "No se encontró el wheel de watcher_segments."
        }
        & $uv.Source pip install --python $venvPython --reinstall --no-deps $wheel.FullName
        if ($LASTEXITCODE -ne 0) {
            throw "uv no pudo instalar watcher_segments."
        }
        Write-Host "Motor nativo Rust instalado." -ForegroundColor Green
    }
    catch {
        Write-Warning "No se pudo preparar el motor nativo: $($_.Exception.Message) Se usará FFmpeg."
    }
}

Write-Host ""
Write-Host "Entorno listo." -ForegroundColor Green
Write-Host "  Python: $venvPython" -ForegroundColor Green
Write-Host "  Ejecuta: .\Start-TheWatcher.ps1" -ForegroundColor Green
