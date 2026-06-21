# setup_env.ps1
# Crea o repara el entorno virtual de Python para ESTE PC.
#
# El venv vive FUERA de OneDrive (en %LOCALAPPDATA%\The Watcher\venv) a proposito:
# un venv contiene rutas absolutas y binarios atados a una maquina/usuario concretos,
# asi que NO debe sincronizarse entre PCs. Cada equipo crea el suyo.
#
# Uso:  powershell -ExecutionPolicy Bypass -File setup_env.ps1
#       (o boton derecho -> "Ejecutar con PowerShell")

$ErrorActionPreference = "Stop"

# -- Rutas --------------------------------------------------------------------
$venvPath   = Join-Path $env:LOCALAPPDATA "The Watcher\venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$reqFile    = Join-Path $PSScriptRoot "project\requirements.txt"

# -- 1. Localizar Python 3.13+ ------------------------------------------------
function Test-PyVersion($exe) {
    try { $v = & $exe --version 2>&1 } catch { return $false }
    # Acepta 3.13..3.19 y 3.20+ (por si sube de version)
    return ($v -match "Python 3\.(1[3-9]|[2-9]\d)")
}

$python = $null

# El py launcher es lo mas fiable en Windows: pedimos explicitamente 3.13+
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $cand = & $pyLauncher.Source -3 -c "import sys; print(sys.executable)" 2>$null
    if ($cand -and (Test-PyVersion $cand)) { $python = $cand }
}
if (-not $python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and (Test-PyVersion $cmd.Source)) { $python = $cmd.Source }
}
if (-not $python) {
    $locations = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
        "$env:ProgramFiles\Python313\python.exe",
        "C:\Python313\python.exe"
    )
    foreach ($loc in $locations) {
        if ((Test-Path $loc) -and (Test-PyVersion $loc)) { $python = $loc; break }
    }
}
if (-not $python) {
    Write-Error "No se encontro Python 3.13+. Instalalo desde https://python.org y vuelve a ejecutar este script."
    exit 1
}
Write-Host "Python: $python ($(& $python --version 2>&1))" -ForegroundColor Cyan

# -- 2. Validar venv existente; recrear si esta roto --------------------------
# En vez de adivinar por el nombre de usuario, simplemente ejecutamos el python
# del venv. Si su Python base ya no existe (otro PC/usuario), fallara y recreamos.
$venvOk = $false
if (Test-Path $venvPython) {
    & $venvPython --version *> $null
    if ($LASTEXITCODE -eq 0) { $venvOk = $true }
}
if ((Test-Path $venvPath) -and (-not $venvOk)) {
    Write-Host "El venv existente esta roto -> recreando..." -ForegroundColor Yellow
    Remove-Item $venvPath -Recurse -Force
}

# -- 3. Crear venv si no existe -----------------------------------------------
if (-not (Test-Path $venvPython)) {
    Write-Host "Creando entorno virtual en $venvPath ..." -ForegroundColor Cyan
    & $python -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { Write-Error "Fallo la creacion del venv."; exit 1 }
}

# -- 4. Instalar dependencias -------------------------------------------------
Write-Host "Actualizando pip..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Error "Fallo al actualizar pip."; exit 1 }

if (Test-Path $reqFile) {
    Write-Host "Instalando requirements.txt..." -ForegroundColor Cyan
    # requirements.txt puede venir en UTF-16 (BOM) generado en otro PC.
    # Get-Content -Raw detecta el BOM automaticamente; lo reescribimos a UTF-8
    # para que pip no se atragante.
    $tmpReq = Join-Path $env:TEMP ("watcher_req_{0}.txt" -f $PID)
    (Get-Content $reqFile -Raw) | Set-Content $tmpReq -Encoding utf8
    & $venvPython -m pip install -r $tmpReq
    $code = $LASTEXITCODE
    Remove-Item $tmpReq -ErrorAction SilentlyContinue
    if ($code -ne 0) { Write-Error "Fallo la instalacion de requirements.txt."; exit 1 }
}

Write-Host ""
Write-Host "Listo. venv preparado para este PC." -ForegroundColor Green
Write-Host "  Ubicacion: $venvPath" -ForegroundColor Green
Write-Host "  Interprete para VS Code: $venvPython" -ForegroundColor Green
