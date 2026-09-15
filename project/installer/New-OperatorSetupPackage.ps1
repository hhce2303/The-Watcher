<#
.SYNOPSIS
    Builds a station-specific Setup executable from an IT provisioning request.

.DESCRIPTION
    This script only packages mkcert for execution on the destination. It does
    not create a CA, leaf certificate, or device identity on the IT PC.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ProvisioningRequest,
    [Parameter(Mandatory)][string]$OutDir,
    [string]$MkcertPath = 'mkcert.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-MkcertExecutable {
    param([string]$Candidate)
    $command = Get-Command $Candidate -ErrorAction SilentlyContinue
    if ($command -and (Test-Path -LiteralPath $command.Source -PathType Leaf)) {
        return $command.Source
    }
    if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
        return (Resolve-Path -LiteralPath $Candidate).Path
    }
    $packages = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    if (Test-Path -LiteralPath $packages -PathType Container) {
        $wingetBinary = Get-ChildItem -LiteralPath $packages -Filter 'mkcert.exe' -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match 'FiloSottile\.mkcert' } |
            Select-Object -First 1
        if ($wingetBinary) { return $wingetBinary.FullName }
    }
    return $null
}

if (-not (Test-Path -LiteralPath $ProvisioningRequest -PathType Leaf)) {
    throw "Provisioning request not found: $ProvisioningRequest"
}
$request = Get-Content -LiteralPath $ProvisioningRequest -Raw -Encoding utf8 | ConvertFrom-Json
if ($request.schema_version -ne 1 -or $request.request_type -ne 'operator_daemon_provisioning') {
    throw 'Unsupported provisioning request.'
}
$mkcert = Get-MkcertExecutable $MkcertPath
if (-not $mkcert) {
    throw 'mkcert is required to build a field setup. Install it on this IT PC with: winget install --id FiloSottile.mkcert -e'
}

$build = Join-Path $PSScriptRoot 'build.ps1'
& $build -OperatorProvisioningRequest (Resolve-Path -LiteralPath $ProvisioningRequest).Path -MkcertPath $mkcert -OutDir $OutDir -RequireInstaller
if ($LASTEXITCODE -ne 0) { throw "The Watcher Setup build failed (exit $LASTEXITCODE)." }
