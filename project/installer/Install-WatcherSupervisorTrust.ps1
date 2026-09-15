<#
.SYNOPSIS
Installs the public test CA used by provisioned The Watcher Operators.

.DESCRIPTION
Run once on each PC/browser profile used by Daily supervisors.  The CA private
key is not included here.  Windows trusts the public root for the current user
only, so this does not change machine-wide trust.
#>
[CmdletBinding()]
param(
    [string]$CertificatePath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $CertificatePath) {
    $operatorRoot = Join-Path $PSScriptRoot 'watcher-operator-rootCA.pem'
    $legacyTestRoot = Join-Path $PSScriptRoot 'watcher-test-rootCA.pem'
    $CertificatePath = if (Test-Path -LiteralPath $operatorRoot -PathType Leaf) {
        $operatorRoot
    } else {
        $legacyTestRoot
    }
}

if (-not (Test-Path -LiteralPath $CertificatePath -PathType Leaf)) {
    throw "Operator public CA certificate not found: $CertificatePath"
}

$certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $CertificatePath
$store = New-Object System.Security.Cryptography.X509Certificates.X509Store 'Root', 'CurrentUser'
try {
    $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    $existing = $store.Certificates | Where-Object Thumbprint -eq $certificate.Thumbprint
    if (-not $existing) {
        $store.Add($certificate)
        Write-Host "Installed The Watcher Operator CA for the current Windows user." -ForegroundColor Green
    } else {
        Write-Host "The Watcher Operator CA is already trusted by the current Windows user." -ForegroundColor Green
    }
} finally {
    $store.Close()
    $certificate.Dispose()
}
