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
#>
param(
    [nullable[bool]]$AutoStart = $null   # $null = ask interactively
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
# Auto-start registration
# ---------------------------------------------------------------------------
if ($null -eq $AutoStart) {
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
# Launch
# ---------------------------------------------------------------------------
$LaunchAnswer = Read-Host "Launch The Watcher now? (Y/n)"
if ($LaunchAnswer -notmatch '^[Nn]') {
    Start-Process -FilePath $ExePath -WorkingDirectory $InstallDir
    Write-Host "The Watcher started." -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Cyan
Write-Host "  Installed at : $InstallDir"
Write-Host "  To uninstall : delete $InstallDir"
