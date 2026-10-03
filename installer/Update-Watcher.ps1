<#
.SYNOPSIS
    In-place update of an installed The Watcher build. Never touches .env or certs\.

.DESCRIPTION
    Run from the freshly extracted build folder (the one containing
    "The Watcher.exe"). It stops the running daemon, replaces the program files
    in the install dir and PRESERVES the machine-specific configuration:
      - .env
      - certs\   (TLS leaf key/cert, issuer public key, trust\*.pem CAs)
    First install: pass -CertsFrom <dir> (a folder with the provisioned certs\
    and/or operator-deployment.env) to seed them once. Existing certs/.env are
    never overwritten unless -Force is given together with -CertsFrom.

.USAGE
    .\Update-Watcher.ps1                                  # update, keep certs
    .\Update-Watcher.ps1 -CertsFrom C:\Provisioning\op1   # first install
    .\Update-Watcher.ps1 -Start                           # relaunch with --daemon
#>
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "The Watcher"),
    [string]$CertsFrom = "",
    [switch]$Force,
    [switch]$Start
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExeName   = "The Watcher.exe"
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $SourceDir $ExeName))) {
    throw "Run Update-Watcher.ps1 from the extracted build folder (missing $ExeName in $SourceDir)."
}
$resolvedInstall = Resolve-Path $InstallDir -ErrorAction SilentlyContinue
if ($resolvedInstall -and ((Resolve-Path $SourceDir).Path -eq $resolvedInstall.Path)) {
    throw "Source and install dir are the same folder; extract the build elsewhere."
}

Write-Host "=== The Watcher update ===" -ForegroundColor Cyan
Write-Host "From: $SourceDir`nTo  : $InstallDir"

# Stop the daemon and orphaned recorder children so files are not locked.
Get-Process -Name "The Watcher" -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name "ffmpeg" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "*The Watcher*" } | Stop-Process -Force
Start-Sleep -Seconds 1

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Drop stale runtime files (same as the Inno installer's InstallDelete); then
# mirror the new build EXCLUDING the preserved config.
$Internal = Join-Path $InstallDir "_internal"
if (Test-Path $Internal) { Remove-Item -Recurse -Force $Internal }

robocopy $SourceDir $InstallDir /E /XD certs /XF .env Update-Watcher.ps1 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }

# Seed config on first install (or -Force), otherwise leave it alone.
$EnvDest   = Join-Path $InstallDir ".env"
$CertsDest = Join-Path $InstallDir "certs"
if ($CertsFrom -ne "") {
    $envSrc   = Join-Path $CertsFrom "operator-deployment.env"
    $certsSrc = Join-Path $CertsFrom "certs"
    if ((Test-Path $envSrc) -and ($Force -or -not (Test-Path $EnvDest))) {
        Copy-Item $envSrc $EnvDest -Force; Write-Host ".env seeded from $envSrc"
    }
    if ((Test-Path $certsSrc) -and ($Force -or -not (Test-Path $CertsDest))) {
        New-Item -ItemType Directory -Force -Path $CertsDest | Out-Null
        Copy-Item "$certsSrc\*" $CertsDest -Recurse -Force; Write-Host "certs seeded from $certsSrc"
    }
}
if (-not (Test-Path $EnvDest)) {
    $example = Join-Path $SourceDir ".env"
    if (Test-Path $example) { Copy-Item $example $EnvDest; Write-Warning ".env created from example - edit it." }
}

if (Test-Path $CertsDest) {
    Write-Host "Preserved certs: $((Get-ChildItem $CertsDest -File).Count) file(s) in $CertsDest" -ForegroundColor Green
} else {
    Write-Warning "No certs\ in $InstallDir. Re-run with -CertsFrom <provisioning dir>."
}

# Trust the CA certificates shipped by the TLS provisioning service in
# certs\trust\*.pem for the current user (idempotent). Needs an interactive
# desktop session: Windows shows a confirmation dialog. Over SSH it fails with
# "request not supported" - run this script locally, or use
# `certutil -addstore Root <ca.pem>` from an elevated prompt (machine-wide).
$TrustDir = Join-Path $CertsDest "trust"
if (Test-Path $TrustDir) {
    foreach ($CaPem in (Get-ChildItem $TrustDir -File -Filter *.pem).FullName) {
        try {
            $ca = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $CaPem
            $trusted = @(Get-ChildItem Cert:\CurrentUser\Root, Cert:\LocalMachine\Root | Where-Object Thumbprint -eq $ca.Thumbprint)
            if ($trusted.Count -gt 0) {
                Write-Host "CA $(Split-Path $CaPem -Leaf) already trusted." -ForegroundColor Green
            } else {
                $store = New-Object System.Security.Cryptography.X509Certificates.X509Store "Root", "CurrentUser"
                $store.Open("ReadWrite"); $store.Add($ca); $store.Close()
                Write-Host "CA $(Split-Path $CaPem -Leaf) trusted for current user." -ForegroundColor Green
            }
        } catch {
            Write-Warning "Could not trust CA ($($_.Exception.Message)). Run locally, or elevated: certutil -addstore Root `"$CaPem`""
        }
    }
}

if ($Start) {
    Start-Process (Join-Path $InstallDir $ExeName) -ArgumentList "--daemon" -WorkingDirectory $InstallDir
    Write-Host "Daemon started."
}
Write-Host "=== Update complete ===" -ForegroundColor Cyan
