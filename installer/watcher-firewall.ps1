# The Watcher - reglas de firewall de la estación Operator.
#
# Uso normal: doble clic en "Configurar firewall.cmd" (misma carpeta). No hay
# nada que editar. Se instala junto a "The Watcher.exe" y toma la ruta del exe
# de su propia carpeta, así funciona aunque IT eleve con otra cuenta.
#
# - Entrada TCP 8767 (vista LAN) en perfiles Domain y Private. Nunca Public.
# - Salida TCP 443 (Daily/Supabase) sólo para The Watcher.exe.
# Idempotente: borra y recrea únicamente las reglas con estos nombres.
# -Remove las elimina.
param(
  [switch]$Remove,
  [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

$LiveViewPort     = 8767
$DailyPort        = 443
$NetworkScope     = @('Domain', 'Private')
$InboundRuleName  = 'The Watcher Live View'
$OutboundRuleName = 'The Watcher outbound Daily HTTPS'
$WatcherExe       = Join-Path $PSScriptRoot 'The Watcher.exe'

function Wait-ForUser {
  if (-not $Quiet) { Read-Host 'Pulse Enter para cerrar' | Out-Null }
}

# Auto-elevación: pide UAC y se relanza con los mismos parámetros.
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
  if ($Remove) { $argList += '-Remove' }
  if ($Quiet)  { $argList += '-Quiet' }
  try {
    $proc = Start-Process -FilePath 'powershell.exe' -ArgumentList $argList -Verb RunAs -Wait -PassThru
    exit $proc.ExitCode
  } catch {
    Write-Host 'Se canceló la elevación. Se necesita una cuenta administradora para crear las reglas.' -ForegroundColor Red
    Wait-ForUser
    exit 1
  }
}

try {
  # Borrar siempre las nuestras primero: corrige reglas viejas (p. ej. sólo
  # Private) y evita duplicados al reinstalar.
  Get-NetFirewallRule -DisplayName $InboundRuleName, $OutboundRuleName -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule

  if ($Remove) {
    Write-Host 'Reglas de The Watcher eliminadas.' -ForegroundColor Green
    Wait-ForUser
    exit 0
  }

  New-NetFirewallRule -DisplayName $InboundRuleName -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort $LiveViewPort -Profile $NetworkScope | Out-Null
  Write-Host "OK  Entrada TCP $LiveViewPort ($($NetworkScope -join ', '))" -ForegroundColor Green

  # Si el script se ejecutó fuera de la carpeta de instalación, usar el exe
  # del proceso que ya escucha en 8767 (ruta real del perfil del Operator).
  if (-not (Test-Path -LiteralPath $WatcherExe -PathType Leaf)) {
    $owner = Get-NetTCPConnection -LocalPort $LiveViewPort -State Listen -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($owner) {
      $running = (Get-Process -Id $owner.OwningProcess -ErrorAction SilentlyContinue).Path
      if ($running -and (Split-Path -Leaf $running) -eq 'The Watcher.exe') { $WatcherExe = $running }
    }
  }

  if (Test-Path -LiteralPath $WatcherExe -PathType Leaf) {
    New-NetFirewallRule -DisplayName $OutboundRuleName -Direction Outbound -Action Allow `
      -Program $WatcherExe -Protocol TCP -RemotePort $DailyPort -Profile Any | Out-Null
    Write-Host "OK  Salida TCP $DailyPort para $WatcherExe" -ForegroundColor Green
  } else {
    Write-Host "AVISO  No se encontró The Watcher.exe junto al script ni en ejecución; no se creó la regla de salida. Inicie The Watcher o ejecute el script desde su carpeta de instalación." -ForegroundColor Yellow
  }

  # Diagnóstico de los dos fallos que ya vimos en el piloto.
  $warnings = 0
  foreach ($network in Get-NetConnectionProfile) {
    if ($network.NetworkCategory -eq 'Public') {
      Write-Host "AVISO  La red '$($network.Name)' es Public: la vista LAN no será accesible. Pida a IT cambiarla a Private o Domain." -ForegroundColor Yellow
      $warnings++
    }
  }
  $blocking = Get-NetFirewallRule -Direction Inbound -Action Block -Enabled True -ErrorAction SilentlyContinue |
    Where-Object { ($_ | Get-NetFirewallPortFilter).LocalPort -contains "$LiveViewPort" }
  foreach ($rule in $blocking) {
    Write-Host "AVISO  La regla '$($rule.DisplayName)' bloquea TCP $LiveViewPort y gana sobre la de permitir." -ForegroundColor Yellow
    $warnings++
  }

  $listening = Get-NetTCPConnection -LocalPort $LiveViewPort -State Listen -ErrorAction SilentlyContinue
  if ($listening) {
    Write-Host "OK  The Watcher escucha en $LiveViewPort." -ForegroundColor Green
  } else {
    Write-Host "INFO  Nada escucha aún en $LiveViewPort (inicie The Watcher)." -ForegroundColor Cyan
  }

  $ips = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -like '192.168.*' }).IPAddress -join ', '
  Write-Host ''
  Write-Host "Listo. Pruebe DESDE OTRO PC: Test-NetConnection $env:COMPUTERNAME -Port $LiveViewPort   (IP: $ips)"
  Wait-ForUser
  if ($warnings -gt 0) { exit 2 } else { exit 0 }
} catch {
  Write-Host "ERROR  $($_.Exception.Message)" -ForegroundColor Red
  Wait-ForUser
  exit 1
}
