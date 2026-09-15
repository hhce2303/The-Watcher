<#
.SYNOPSIS
    Finalizes a provisioned Operator install on the destination PC.

.DESCRIPTION
    Runs from Inno Setup under the interactive Operator user.  It is the only
    place that creates the local mkcert CA/leaf and writes runtime settings.
    No private certificate or device identity is received from IT.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$InstallDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$install = [IO.Path]::GetFullPath($InstallDir)
$requestPath = Join-Path $install 'operator-provisioning.json'
$mkcert = Join-Path $install 'tools\mkcert.exe'
if (-not (Test-Path -LiteralPath $requestPath -PathType Leaf)) {
    throw "Provisioning request not found: $requestPath"
}
if (-not (Test-Path -LiteralPath $mkcert -PathType Leaf)) {
    throw "Bundled mkcert was not found: $mkcert"
}

$request = Get-Content -LiteralPath $requestPath -Raw -Encoding utf8 | ConvertFrom-Json
if ($request.schema_version -ne 1 -or $request.request_type -ne 'operator_daemon_provisioning') {
    throw 'Unsupported The Watcher provisioning request.'
}
$stationId = [int]$request.station.id_station
$stationNumber = [string]$request.station.station_number
$endpoint = ([string]$request.station.endpoint_hint).Trim()
if ($stationId -lt 1 -or [string]::IsNullOrWhiteSpace($stationNumber)) {
    throw 'The provisioning request has an invalid station identity.'
}

$certDir = Join-Path $install 'certs'
$caRoot = Join-Path $certDir 'mkcert'
New-Item -ItemType Directory -Force -Path $certDir, $caRoot | Out-Null

# CAROOT is product-local and belongs to the Operator account.  mkcert -install
# places only its public root in that account's trust store; rootCA-key.pem never
# leaves this PC and is not copied to a Supervisor package.
$previousCaroot = $env:CAROOT
try {
    $env:CAROOT = $caRoot
    & $mkcert -install
    if ($LASTEXITCODE -ne 0) { throw "mkcert could not initialize the local CA (exit $LASTEXITCODE)." }

    $rootCertificate = Join-Path $caRoot 'rootCA.pem'
    if (-not (Test-Path -LiteralPath $rootCertificate -PathType Leaf)) {
        throw 'mkcert did not create the local public root certificate.'
    }
    $leafCertificate = Join-Path $certDir 'live-view.pem'
    $leafKey = Join-Path $certDir 'live-view-key.pem'
    $sans = @('localhost', '127.0.0.1')
    if ($endpoint) { $sans += $endpoint }
    & $mkcert -cert-file $leafCertificate -key-file $leafKey @($sans | Select-Object -Unique)
    if ($LASTEXITCODE -ne 0) { throw "mkcert could not create the local TLS certificate (exit $LASTEXITCODE)." }
    Copy-Item -LiteralPath $rootCertificate -Destination (Join-Path $certDir 'watcher-operator-rootCA.pem') -Force
} finally {
    $env:CAROOT = $previousCaroot
}

# Daily's assertion key is public.  Downloading it on the destination ensures
# the setup carries no stale signing key from the IT workstation.
$assertionUrl = 'https://gbtmbuzlnxdjcexppomf.supabase.co/functions/v1/watcher-assertion-public-key'
try {
    $issuer = Invoke-RestMethod -Uri $assertionUrl -Method Get -TimeoutSec 30
} catch {
    throw "Could not obtain Daily's public assertion key: $($_.Exception.Message)"
}
if (-not $issuer.public_jwk -or -not $issuer.kid) {
    throw 'Daily returned an invalid assertion public-key document.'
}
$issuerFile = Join-Path $certDir 'daily-issuer-public.pem'
[IO.File]::WriteAllText($issuerFile, ($issuer.public_jwk | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))

$liveEnabled = -not [string]::IsNullOrWhiteSpace($endpoint)
$profile = @(
    "BROWSER_LOCAL_ENABLED=true"
    "BROWSER_LOCAL_PARENT_ORIGIN=https://daily.sig.systems"
    "BROWSER_LOCAL_ISSUER=daily.sig.systems"
    "BROWSER_LOCAL_AUDIENCE=the-watcher-local"
    "BROWSER_LOCAL_ISSUER_KID=$($issuer.kid)"
    "BROWSER_LOCAL_STATION_ID=$stationId"
    "BROWSER_LOCAL_CERT_FILE=certs\\live-view.pem"
    "BROWSER_LOCAL_KEY_FILE=certs\\live-view-key.pem"
    "BROWSER_LOCAL_ISSUER_PUBLIC_KEY_FILE=certs\\daily-issuer-public.pem"
    "LIVE_VIEW_ENABLED=$($liveEnabled.ToString().ToLowerInvariant())"
    "LIVE_VIEW_BIND_HOST=0.0.0.0"
    "LIVE_VIEW_PORT=8767"
    "LIVE_VIEW_PARENT_ORIGIN=https://daily.sig.systems"
    "LIVE_VIEW_ISSUER=daily.sig.systems"
    "LIVE_VIEW_AUDIENCE=the-watcher-live"
    "LIVE_VIEW_ISSUER_KID=$($issuer.kid)"
    "LIVE_VIEW_STATION_ID=$stationId"
    "LIVE_VIEW_CERT_FILE=certs\\live-view.pem"
    "LIVE_VIEW_KEY_FILE=certs\\live-view-key.pem"
    "LIVE_VIEW_ISSUER_PUBLIC_KEY_FILE=certs\\daily-issuer-public.pem"
    "LIVE_VIEW_HEARTBEAT_URL=https://gbtmbuzlnxdjcexppomf.supabase.co/functions/v1/watcher-heartbeat"
    "LIVE_VIEW_HEARTBEAT_SECONDS=30"
    "LIVE_VIEW_MAX_VIEWERS=3"
)
if ($liveEnabled) { $profile += "LIVE_VIEW_ORIGIN=https://${endpoint}:8767" }
[IO.File]::WriteAllLines((Join-Path $install '.env'), $profile, [Text.UTF8Encoding]::new($false))
if ($liveEnabled) {
    [IO.File]::WriteAllText((Join-Path $install 'live-view-enabled.flag'), '', [Text.UTF8Encoding]::new($false))
} else {
    Remove-Item -LiteralPath (Join-Path $install 'live-view-enabled.flag') -Force -ErrorAction SilentlyContinue
}

# This contains the public root only. IT can copy it to the Supervisor and run
# Install-WatcherSupervisorTrust.ps1; never copy the mkcert directory itself.
$trustDir = Join-Path $install 'supervisor-trust'
New-Item -ItemType Directory -Force -Path $trustDir | Out-Null
Copy-Item -LiteralPath (Join-Path $certDir 'watcher-operator-rootCA.pem') -Destination (Join-Path $trustDir 'watcher-operator-rootCA.pem') -Force
$trustScript = Join-Path $install 'Install-WatcherSupervisorTrust.ps1'
if (Test-Path -LiteralPath $trustScript) {
    Copy-Item -LiteralPath $trustScript -Destination (Join-Path $trustDir 'Install-WatcherSupervisorTrust.ps1') -Force
}

Write-Host "The Watcher station $stationNumber (ID $stationId) is provisioned." -ForegroundColor Green
Write-Host "Supervisor public trust package: $trustDir" -ForegroundColor Yellow
