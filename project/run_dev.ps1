<#
.SYNOPSIS
    Runs The Watcher directly from the dev venv — no build/install needed.

.DESCRIPTION
    Activates the local project venv and launches app/main.py.
    Use this for rapid iteration instead of running build.ps1 + install.ps1.

.USAGE
    cd project
    .\run_dev.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ScriptDir "venv\Scripts\python.exe"
$MainPy     = Join-Path $ScriptDir "app\main.py"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Dev venv not found at $VenvPython. Run: python -m venv venv && venv\Scripts\pip install -r requirements\requirements.txt"
}

if (-not (Test-Path $MainPy)) {
    Write-Error "Cannot find app\main.py in $ScriptDir"
}

Write-Host "=== The Watcher (dev mode) ===" -ForegroundColor Cyan
Write-Host "Python : $VenvPython" -ForegroundColor Gray
Write-Host "Entry  : $MainPy"     -ForegroundColor Gray
Write-Host ""

# Run from the project root so relative imports resolve correctly
Set-Location $ScriptDir
& $VenvPython $MainPy @args
