# The Watcher - datos públicos para enrolar la estación en Daily.
#
# Uso normal: doble clic en "Datos de enrolamiento.cmd" (o Inicio ->
# "Datos de enrolamiento de The Watcher") con la sesión del Operator. No pide
# administrador ni hay nada que editar.
#
# Muestra y copia al portapapeles exactamente los campos del formulario
# Administración -> Dispositivos Watcher. Sólo lee device_id y public_key_pem:
# la clave privada del archivo de identidad nunca se muestra ni se copia.
param([switch]$Quiet)

$ErrorActionPreference = 'Stop'

function Wait-ForUser {
  if (-not $Quiet) { Read-Host 'Pulse Enter para cerrar' | Out-Null }
}

function Read-Profile([string]$path) {
  $values = @{}
  if (Test-Path -LiteralPath $path -PathType Leaf) {
    foreach ($line in Get-Content -LiteralPath $path) {
      if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$') { $values[$Matches[1]] = $Matches[2] }
    }
  }
  return $values
}

try {
  $envFile = Read-Profile (Join-Path $PSScriptRoot '.env')

  $stationId = $envFile['LIVE_VIEW_STATION_ID']
  if (-not ($stationId -match '^[1-9][0-9]*$')) {
    throw "LIVE_VIEW_STATION_ID no está configurado en $PSScriptRoot\.env. Reinstale con el instalador de esta estación."
  }

  $dataDir = $envFile['BROWSER_LOCAL_DATA_DIR']
  if (-not $dataDir) { $dataDir = Join-Path $PSScriptRoot 'browser_local' }
  $identityPath = Join-Path $dataDir 'device_identity.json'
  if (-not (Test-Path -LiteralPath $identityPath -PathType Leaf)) {
    throw "Aún no existe la identidad del dispositivo ($identityPath). Inicie The Watcher, espere unos segundos y vuelva a ejecutar."
  }

  # Sólo los dos campos públicos salen de este bloque.
  $public = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json |
    Select-Object device_id, public_key_pem
  if (-not $public.device_id -or $public.public_key_pem -notmatch 'BEGIN PUBLIC KEY') {
    throw "El archivo de identidad está incompleto: $identityPath. No lo edite; avise a IT."
  }

  $origin = $envFile['LIVE_VIEW_ORIGIN']
  $displayName = "$env:COMPUTERNAME - Operator"

  $block = @"
=== The Watcher - enrolamiento en Daily ===
Daily -> Administración -> Dispositivos Watcher -> Crear/actualizar

device_id:      $($public.device_id)
station_id:     $stationId
Nombre visible: $displayName
Estado:         activo
public_key_pem:
$($public.public_key_pem.Trim())

Endpoint LAN:   $origin
Equipo:         $env:COMPUTERNAME  ($env:USERNAME)
"@

  Write-Host $block
  try {
    Set-Clipboard -Value $block
    Write-Host ''
    Write-Host 'OK  Copiado al portapapeles. Péguelo en el canal de IT o directamente en Daily.' -ForegroundColor Green
  } catch {
    Write-Host 'AVISO  No se pudo copiar al portapapeles; seleccione y copie el texto de arriba.' -ForegroundColor Yellow
  }
  Wait-ForUser
  exit 0
} catch {
  Write-Host "ERROR  $($_.Exception.Message)" -ForegroundColor Red
  Wait-ForUser
  exit 1
}
