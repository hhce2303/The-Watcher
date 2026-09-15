<#
.SYNOPSIS
Creates the provisioned HTTPS profile consumed by build.ps1 for one Operator.

.DESCRIPTION
This is deliberately run on the protected provisioning workstation, not on an
Operator PC.  It creates one shared test CA in ProvisioningRoot and a distinct
TLS leaf key/certificate for the named Operator.  Only the leaf key is copied
into that Operator's installer.  The CA private key never leaves
ProvisioningRoot; the public root is emitted as a separate Supervisor trust
package.

The resulting operator-deployment.env can be passed directly to build.ps1:
  .\build.ps1 -OperatorDeploymentConfig <output>\operator-deployment.env

mkcert is free.  Install it once on the provisioning computer with:
  winget install --id FiloSottile.mkcert -e
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$StationName,

    [Parameter(Mandatory)]
    [ValidateRange(1, 2147483647)]
    [int]$StationId,

    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9.-]*$')]
    [string]$EndpointName,

    [string[]]$IpAddress = @(),

    [string]$DailyIssuerPublicKeyPath,

    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$DailyIssuerKid,

    [string]$DailyAssertionPublicKeyUrl = 'https://gbtmbuzlnxdjcexppomf.supabase.co/functions/v1/watcher-assertion-public-key',

    [string]$ProvisioningRoot = 'C:\Watcher-Provisioning',
    [string]$MkcertPath = 'mkcert.exe',
    [switch]$BuildInstaller,
    [string]$OutDir = '',
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-MkcertCommand {
    param([string]$Candidate)
    $command = Get-Command $Candidate -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
        return (Resolve-Path -LiteralPath $Candidate).Path
    }
    $wingetPackageRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    $wingetMkcert = Get-ChildItem -Path $wingetPackageRoot -Filter 'mkcert.exe' -Recurse -File -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($wingetMkcert) { return $wingetMkcert.FullName }
    throw "mkcert was not found. Install it on this provisioning computer with: winget install --id FiloSottile.mkcert -e"
}

function Assert-IpAddress {
    param([string]$Value)
    $parsed = $null
    if (-not [System.Net.IPAddress]::TryParse($Value, [ref]$parsed)) {
        throw "Invalid IP address: $Value"
    }
}

$mkcert = Get-MkcertCommand $MkcertPath
$provisioning = [System.IO.Path]::GetFullPath($ProvisioningRoot)
$caRoot = Join-Path $provisioning 'test-ca'
$stationRoot = Join-Path (Join-Path $provisioning 'operators') $StationName
$certDirectory = Join-Path $stationRoot 'certs'
$trustDirectory = Join-Path $provisioning 'supervisor-trust'

foreach ($address in $IpAddress) { Assert-IpAddress $address }
New-Item -ItemType Directory -Force -Path $caRoot, $trustDirectory | Out-Null

if ((Test-Path -LiteralPath $stationRoot) -and -not $Force) {
    throw "Provisioning output already exists: $stationRoot. Use -Force only when intentionally rotating this station's certificate."
}
New-Item -ItemType Directory -Force -Path $certDirectory | Out-Null

if ($DailyIssuerPublicKeyPath) {
    if (-not (Test-Path -LiteralPath $DailyIssuerPublicKeyPath -PathType Leaf)) {
        throw "Daily issuer public key not found: $DailyIssuerPublicKeyPath"
    }
    $issuerKeyText = Get-Content -LiteralPath $DailyIssuerPublicKeyPath -Raw -Encoding utf8
} else {
    try {
        $issuerResponse = Invoke-RestMethod -Uri $DailyAssertionPublicKeyUrl -Method Get -TimeoutSec 20
    } catch {
        throw "Could not download Daily's public assertion key from ${DailyAssertionPublicKeyUrl}: $($_.Exception.Message)"
    }
    if (-not $issuerResponse.public_jwk -or -not $issuerResponse.kid) {
        throw 'Daily returned an invalid assertion public-key document.'
    }
    $issuerKeyText = $issuerResponse.public_jwk | ConvertTo-Json -Compress
    if (-not $DailyIssuerKid) { $DailyIssuerKid = [string]$issuerResponse.kid }
}
if (-not $DailyIssuerKid) {
    throw 'DailyIssuerKid is required when DailyIssuerPublicKeyPath is supplied.'
}

# CAROOT keeps rootCA-key.pem out of the repository and out of every installer.
$previousCaroot = $env:CAROOT
try {
    $env:CAROOT = $caRoot
    & $mkcert -install
    if ($LASTEXITCODE -ne 0) { throw "mkcert could not create/install the test CA (exit $LASTEXITCODE)." }

    $rootCertificate = Join-Path $caRoot 'rootCA.pem'
    if (-not (Test-Path -LiteralPath $rootCertificate -PathType Leaf)) {
        throw "mkcert did not produce $rootCertificate"
    }

    $leafCertificate = Join-Path $certDirectory 'live-view.pem'
    $leafKey = Join-Path $certDirectory 'live-view-key.pem'
    # One leaf is used by both surfaces: LAN uses the managed endpoint, while
    # the Operator's own Daily preview is pinned to loopback:8765.
    $sanNames = @($EndpointName, 'localhost', '127.0.0.1') + $IpAddress | Select-Object -Unique
    & $mkcert -cert-file $leafCertificate -key-file $leafKey $sanNames
    if ($LASTEXITCODE -ne 0) { throw "mkcert could not create the Operator certificate (exit $LASTEXITCODE)." }
} finally {
    $env:CAROOT = $previousCaroot
}

foreach ($requiredFile in @($leafCertificate, $leafKey)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Missing generated TLS asset: $requiredFile"
    }
}

[System.IO.File]::WriteAllText((Join-Path $certDirectory 'daily-issuer-public.pem'), $issuerKeyText, [System.Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath (Join-Path $caRoot 'rootCA.pem') -Destination (Join-Path $trustDirectory 'watcher-test-rootCA.pem') -Force
Copy-Item -LiteralPath (Join-Path $caRoot 'rootCA.pem') -Destination (Join-Path $certDirectory 'watcher-test-rootCA.pem') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Install-WatcherSupervisorTrust.ps1') -Destination (Join-Path $trustDirectory 'Install-WatcherSupervisorTrust.ps1') -Force

$origin = "https://$EndpointName`:8767"
$profile = @(
    'LIVE_VIEW_ENABLED=true'
    'LIVE_VIEW_BIND_HOST=0.0.0.0'
    'LIVE_VIEW_PORT=8767'
    "LIVE_VIEW_ORIGIN=$origin"
    'LIVE_VIEW_PARENT_ORIGIN=https://daily.sig.systems'
    'LIVE_VIEW_ISSUER=daily.sig.systems'
    'LIVE_VIEW_AUDIENCE=the-watcher-live'
    "LIVE_VIEW_ISSUER_KID=$DailyIssuerKid"
    "LIVE_VIEW_STATION_ID=$StationId"
    'LIVE_VIEW_CERT_FILE=certs\\live-view.pem'
    'LIVE_VIEW_KEY_FILE=certs\\live-view-key.pem'
    'LIVE_VIEW_ISSUER_PUBLIC_KEY_FILE=certs\\daily-issuer-public.pem'
    'LIVE_VIEW_HEARTBEAT_URL=https://gbtmbuzlnxdjcexppomf.supabase.co/functions/v1/watcher-heartbeat'
    'LIVE_VIEW_HEARTBEAT_SECONDS=30'
    'LIVE_VIEW_MAX_VIEWERS=3'
    'BROWSER_LOCAL_ENABLED=true'
    'BROWSER_LOCAL_PARENT_ORIGIN=https://daily.sig.systems'
    'BROWSER_LOCAL_ISSUER=daily.sig.systems'
    'BROWSER_LOCAL_AUDIENCE=the-watcher-local'
    "BROWSER_LOCAL_ISSUER_KID=$DailyIssuerKid"
    "BROWSER_LOCAL_STATION_ID=$StationId"
    'BROWSER_LOCAL_CERT_FILE=certs\\live-view.pem'
    'BROWSER_LOCAL_KEY_FILE=certs\\live-view-key.pem'
    'BROWSER_LOCAL_ISSUER_PUBLIC_KEY_FILE=certs\\daily-issuer-public.pem'
)
$profilePath = Join-Path $stationRoot 'operator-deployment.env'
[System.IO.File]::WriteAllLines($profilePath, $profile, [System.Text.UTF8Encoding]::new($false))

if ($BuildInstaller) {
    $buildScript = Join-Path $PSScriptRoot 'build.ps1'
    if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
        throw "The build script was not found: $buildScript"
    }
    $buildArguments = @{ OperatorDeploymentConfig = $profilePath; RequireInstaller = $true }
    if (-not $OutDir) { $OutDir = Join-Path $stationRoot 'release' }
    $buildArguments.OutDir = $OutDir
    & $buildScript @buildArguments
    if ($LASTEXITCODE -ne 0) { throw "The Watcher installer build failed (exit $LASTEXITCODE)." }
}

[pscustomobject]@{
    StationName = $StationName
    StationId = $StationId
    LiveViewOrigin = $origin
    DeploymentProfile = $profilePath
    SupervisorTrustPackage = $trustDirectory
    NextCommand = ".\\build.ps1 -OperatorDeploymentConfig `"$profilePath`""
} | Format-List
