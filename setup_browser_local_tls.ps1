<#
.SYNOPSIS
    Creates the trusted loopback TLS certificate used by The Watcher's Daily
    SIG Systems browser-local iframe.

.DESCRIPTION
    The certificate and private key stay in the current Windows user's
    LocalAppData profile. This script never enables the listener and never
    writes Daily's assertion-verification key: enrolment/site configuration is
    still an explicit deployment step after the Edge Function is configured.
#>
[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $env:LOCALAPPDATA "The Watcher\browser_local")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$mkcert = Get-Command mkcert.exe -ErrorAction SilentlyContinue
if ($null -eq $mkcert) { $mkcert = Get-Command mkcert -ErrorAction SilentlyContinue }
if ($null -eq $mkcert) {
    # Winget's per-user package location is not always added to PATH until a
    # new Windows logon. Find the installed executable without guessing a
    # versioned package directory.
    $wingetPackageRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $wingetPackageRoot) {
        $mkcert = Get-ChildItem -LiteralPath $wingetPackageRoot -Recurse -Filter "mkcert.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1
    }
}
if ($null -eq $mkcert) {
    throw "mkcert no está instalado o no está en PATH. Instálalo con: winget install FiloSottile.mkcert"
}
$mkcertPath = if ($null -ne $mkcert.PSObject.Properties["Source"] -and $mkcert.Source) {
    $mkcert.Source
} else {
    $mkcert.FullName
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$certFile = Join-Path $OutputDirectory "localhost.pem"
$keyFile = Join-Path $OutputDirectory "localhost-key.pem"

Write-Host "Instalando/verificando la CA local de mkcert..." -ForegroundColor Cyan
& $mkcertPath -install
if ($LASTEXITCODE -ne 0) { throw "mkcert -install falló con código $LASTEXITCODE." }

Write-Host "Creando certificado TLS loopback..." -ForegroundColor Cyan
& $mkcertPath -cert-file $certFile -key-file $keyFile localhost 127.0.0.1 ::1
if ($LASTEXITCODE -ne 0) { throw "mkcert no pudo crear el certificado local." }

try {
    $identity = "$env:USERDOMAIN\$env:USERNAME"
    & icacls $keyFile /inheritance:r /grant:r "$identity`:(R,W)" | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warning "No se pudo restringir el ACL de '$keyFile'; revísalo antes de habilitar el piloto." }
} catch {
    Write-Warning "No se pudo restringir el ACL de '$keyFile': $($_.Exception.Message)"
}

Write-Host "TLS local listo:" -ForegroundColor Green
Write-Host "  BROWSER_LOCAL_CERT_FILE=$certFile"
Write-Host "  BROWSER_LOCAL_KEY_FILE=$keyFile"
Write-Host "Sigue el handoff: importa la clave pública del Edge Function, fija BROWSER_LOCAL_SITE_ID y habilita BROWSER_LOCAL_ENABLED=true sólo después de enrolar el dispositivo." -ForegroundColor Yellow
