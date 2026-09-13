<#
.SYNOPSIS
    Installs The Watcher on the current Windows machine.

.DESCRIPTION
    Copies the application to %LOCALAPPDATA%\The Watcher and
    optionally registers auto-start at login.
    No desktop shortcut is created.

.USAGE
    # Run from the folder containing The Watcher.exe:
    .\install.ps1

    # Skip auto-start prompt:
    .\install.ps1 -AutoStart $false

    # Unattended operator deploy (pre-seeds role=operator, copies a
    # site-specific .env, runs enrollment, launches --daemon with no prompts
    # except the NAS path, which can also be passed via -SlcStorageHost):
    .\install.ps1 -Unattended -EnvFile .\site.env -SlcStorageHost '\\SIG-SLC-Storage'
#>
param(
    [nullable[bool]]$AutoStart = $null,   # $null = ask interactively (ignored when -Unattended)
    [switch]$Unattended,
    [string]$EnvFile = "",
    [string]$SlcStorageHost = ""          # UNC path where recordings are browsed from; "" = ask interactively
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$AppName     = "The Watcher"
$ExeName     = "The Watcher.exe"
$InstallDir  = Join-Path $env:LOCALAPPDATA $AppName
$SourceDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExeSource   = Join-Path $SourceDir $ExeName

if (-not (Test-Path $ExeSource)) {
    Write-Error "Cannot find $ExeName in $SourceDir. Run install.ps1 from the The Watcher folder."
}

Write-Host "=== The Watcher Installer ===" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# Copy application files
# ---------------------------------------------------------------------------
Write-Host "Installing to $InstallDir ..."
if (Test-Path $InstallDir) {
    # Stop running instance if present
    $proc = Get-Process -Name $AppName -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Stopping running instance..."
        $proc | Stop-Process -Force
        $proc | Wait-Process -Timeout 15 -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }
    # Also kill any orphaned ffmpeg child processes left by the recorder
    Get-Process -Name "ffmpeg" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -like "*The Watcher*" -or $_.Path -like "*AppData\Local\The Watcher*" } |
        ForEach-Object { $_ | Stop-Process -Force; $_ | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue }
}
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item -Recurse -Force "$SourceDir\*" "$InstallDir\"
Write-Host "Files copied." -ForegroundColor Green

# ---------------------------------------------------------------------------
# Unattended deploy: pre-seed the operator role and the site-specific .env
# ---------------------------------------------------------------------------
$UserConfigPath = Join-Path $env:LOCALAPPDATA "The Watcher\user_config.json"
if ($Unattended) {
    if (-not (Test-Path $UserConfigPath)) {
        New-Item -ItemType Directory -Path (Split-Path $UserConfigPath) -Force | Out-Null
        '{"role": "operator"}' | Set-Content -Path $UserConfigPath -Encoding utf8
        Write-Host "Pre-seeded role=operator at $UserConfigPath" -ForegroundColor Green
    } else {
        Write-Host "user_config.json already exists -- leaving the persisted role untouched." -ForegroundColor Yellow
    }

    if ($EnvFile -ne "") {
        if (-not (Test-Path $EnvFile)) {
            Write-Error "EnvFile '$EnvFile' not found."
        }
        Copy-Item $EnvFile (Join-Path $InstallDir ".env") -Force
        Write-Host "Copied $EnvFile as .env" -ForegroundColor Green
    }
}

# ---------------------------------------------------------------------------
# NAS path: where recordings are browsed from by IT/Supervisor (SLC_STORAGE_HOST)
# ---------------------------------------------------------------------------
function Set-EnvValue {
    param([string]$Path, [string]$Key, [string]$Value)
    $lines = if (Test-Path $Path) { @(Get-Content -Path $Path -Encoding utf8) } else { @() }
    $pattern = "^#?$([regex]::Escape($Key))="
    $newLine = "$Key=$Value"
    $replaced = $false
    $lines = $lines | ForEach-Object {
        if (-not $replaced -and $_ -match $pattern) { $replaced = $true; $newLine } else { $_ }
    }
    if (-not $replaced) { $lines += $newLine }
    Set-Content -Path $Path -Value $lines -Encoding utf8
}

if ($SlcStorageHost -eq "") {
    $defaultNas = "\\SIG-SLC-Storage"
    $answerNas = Read-Host "Ruta UNC del NAS donde quedaran las grabaciones (SLC_STORAGE_HOST) [$defaultNas]"
    $SlcStorageHost = if ($answerNas -eq "") { $defaultNas } else { $answerNas }
}
$EnvPath = Join-Path $InstallDir ".env"
Set-EnvValue -Path $EnvPath -Key "SLC_STORAGE_HOST" -Value $SlcStorageHost
Write-Host "SLC_STORAGE_HOST establecido en $SlcStorageHost" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Auto-start registration (skipped for unattended operator deploys: the
# app's own Scheduled Task watchdog is the sole launcher -- see
# app/core/role.py::_setup_operator_launcher)
# ---------------------------------------------------------------------------
if ($Unattended) {
    $AutoStart = $false
} elseif ($null -eq $AutoStart) {
    $answer = Read-Host "Register The Watcher to start automatically at Windows login? (y/N)"
    $AutoStart = $answer -match '^[Yy]'
}

$RegKey  = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$ExePath = Join-Path $InstallDir $ExeName

if ($AutoStart) {
    Set-ItemProperty -Path $RegKey -Name $AppName -Value "`"$ExePath`""
    Write-Host "Auto-start registered." -ForegroundColor Green
} else {
    # Remove any previous registration
    Remove-ItemProperty -Path $RegKey -Name $AppName -ErrorAction SilentlyContinue
    Write-Host "Auto-start not registered."
}

# ---------------------------------------------------------------------------
# Enrollment: generate/read the Daily browser-local identity + TLS cert
# ---------------------------------------------------------------------------
$EnrollExe = Join-Path $InstallDir "The Watcher Enroll.exe"
if (Test-Path $EnrollExe) {
    Write-Host ""
    Write-Host "=== Enrollment (Daily SIG Systems) ===" -ForegroundColor Cyan
    & $EnrollExe
}

# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------
if ($Unattended) {
    Start-Process -FilePath $ExePath -ArgumentList "--daemon" -WorkingDirectory $InstallDir
    Write-Host "The Watcher started in daemon mode." -ForegroundColor Green
} else {
    $LaunchAnswer = Read-Host "Launch The Watcher now? (Y/n)"
    if ($LaunchAnswer -notmatch '^[Nn]') {
        Start-Process -FilePath $ExePath -WorkingDirectory $InstallDir
        Write-Host "The Watcher started." -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Cyan
Write-Host "  Installed at : $InstallDir"
Write-Host "  To uninstall : delete $InstallDir"
