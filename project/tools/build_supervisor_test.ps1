<#
.SYNOPSIS
    Compila supervisor_test.py en un .exe standalone sin dependencias.

.DESCRIPTION
    Crea un venv minimo con websockets + pyinstaller y genera
    dist\supervisor_test\supervisor_test.exe  (console app).

.USAGE
    # Desde el directorio tools\:
    .\build_supervisor_test.ps1
#>

Set-StrictMode -Version Latest

$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script   = Join-Path $ToolsDir "supervisor_test.py"
# Use a comma-free path — Qt/PyInstaller break when the venv path contains a comma
# (same issue as the main build.ps1 which uses C:\TW_Venv for the same reason).
$VenvDir  = "C:\TW_SupTest"
$DistDir  = Join-Path $ToolsDir "dist"

Write-Host ""
Write-Host "=== supervisor_test builder ===" -ForegroundColor Cyan
Write-Host "Script : $Script"
Write-Host "Output : $DistDir\supervisor_test.exe"
Write-Host ""

# ── Venv ──────────────────────────────────────────────────────────────────
$Pip          = "$VenvDir\Scripts\pip.exe"
$PyInstaller  = "$VenvDir\Scripts\pyinstaller.exe"

if (-not (Test-Path $PyInstaller)) {
    Write-Host "Creando venv de build en $VenvDir ..." -ForegroundColor Yellow
    if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir }
    python -m venv $VenvDir
    & $Pip install --upgrade pip --quiet
    & $Pip install websockets pyinstaller --quiet
    Write-Host "Venv listo." -ForegroundColor Green
} else {
    Write-Host "Usando venv existente." -ForegroundColor Green
}

# ── PyInstaller ───────────────────────────────────────────────────────────
Write-Host "Compilando..." -ForegroundColor Cyan

Push-Location $ToolsDir
try {
    & $PyInstaller `
        --onefile `
        --console `
        --name "supervisor_test" `
        --distpath "$DistDir" `
        --workpath "$ToolsDir\.build_work" `
        --specpath "$ToolsDir\.build_work" `
        --noconfirm `
        $Script
} finally {
    Pop-Location
}

$Exe = Join-Path $DistDir "supervisor_test.exe"
if (Test-Path $Exe) {
    Write-Host ""
    Write-Host "=== Compilacion exitosa ===" -ForegroundColor Green
    Write-Host "  Ejecutable : $Exe"
    Write-Host ""
    Write-Host "Uso rapido:" -ForegroundColor Cyan
    Write-Host "  supervisor_test.exe <IP_DEL_PC_IT>"
    Write-Host "  supervisor_test.exe 192.168.101.164"
    Write-Host "  supervisor_test.exe 192.168.101.164 --wait 60"
    Write-Host ""
} else {
    Write-Error "La compilacion fallo - no se encontro $Exe"
}
