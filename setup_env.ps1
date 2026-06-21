# setup_env.ps1
# Run this script once on each PC to create a local virtual environment.
# Works regardless of username or Python installation path.
# Usage: Right-click -> "Run with PowerShell"  or:  powershell -ExecutionPolicy Bypass -File setup_env.ps1

$ErrorActionPreference = "Stop"

$venvPath = Join-Path $PSScriptRoot ".venv"

# ── 1. Find Python 3.13 ──────────────────────────────────────────────────────
$python = $null

$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd) {
    $ver = & $cmd.Source --version 2>&1
    if ($ver -match "Python 3\.1[3-9]") { $python = $cmd.Source }
}
if (-not $python) {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) {
        $ver = & $cmd.Source --version 2>&1
        if ($ver -match "Python 3\.1[3-9]") { $python = $cmd.Source }
    }
}
if (-not $python) {
    $locations = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "C:\Python313\python.exe"
    )
    foreach ($loc in $locations) {
        if (Test-Path $loc) { $python = $loc; break }
    }
}
if (-not $python) {
    Write-Error "Python 3.13+ not found. Please install it from https://python.org and re-run this script."
    exit 1
}
Write-Host "Using Python: $python ($( & $python --version 2>&1 ))" -ForegroundColor Cyan

# ── 2. Recreate .venv if it belongs to a different machine ──────────────────
if (Test-Path "$venvPath\pyvenv.cfg") {
    $cfg = Get-Content "$venvPath\pyvenv.cfg" -Raw
    $escapedUser = [regex]::Escape($env:USERNAME)
    if ($cfg -notmatch $escapedUser) {
        Write-Host ".venv was created by a different user -- recreating..." -ForegroundColor Yellow
        Remove-Item $venvPath -Recurse -Force
    }
}

# ── 3. Create venv if it doesn't exist ──────────────────────────────────────
if (-not (Test-Path "$venvPath\Scripts\python.exe")) {
    Write-Host "Creating virtual environment at $venvPath ..." -ForegroundColor Cyan
    & $python -m venv $venvPath
}

$pip = "$venvPath\Scripts\pip.exe"

# ── 4. Install packages ──────────────────────────────────────────────────────
Write-Host "Installing packages..." -ForegroundColor Cyan

# Core UI + runtime (not in requirements.txt)
& $pip install --quiet PySide6 screeninfo

# requirements.txt (handle UTF-16 BOM encoding produced by the other PC)
$reqFile = Join-Path $PSScriptRoot "project\requirements.txt"
if (Test-Path $reqFile) {
    $raw = Get-Content $reqFile -Encoding Unicode -Raw
    $tmpReq = [System.IO.Path]::GetTempFileName() + ".txt"
    $raw | Set-Content $tmpReq -Encoding utf8
    & $pip install --quiet -r $tmpReq
    Remove-Item $tmpReq -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Setup complete! .venv is ready for this machine." -ForegroundColor Green
Write-Host "In VS Code select the interpreter: .venv\Scripts\python.exe" -ForegroundColor Green
