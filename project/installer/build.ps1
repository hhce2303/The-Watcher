<#
.SYNOPSIS
    Builds the The Watcher Windows executable (Milestone 8).

.DESCRIPTION
    1. Creates a clean build venv at C:\TW_Venv (comma-free path) to work
       around a Qt/PyInstaller bug where QLibraryInfo.path() mis-parses the
       PySide6 plugins directory when the venv path contains a comma.
    2. Creates a junction C:\TW_Build -> project root (also comma-free) so
       PyInstaller's pathex/spec work correctly.
    3. Runs PyInstaller with the spec file.
    4. Copies .env.example to dist/The Watcher/ as .env.
    5. Creates dist/The Watcher.zip for distribution.

.USAGE
    # From the project/ directory:
    .\installer\build.ps1

    # Or supply a custom output directory:
    .\installer\build.ps1 -OutDir "C:\Builds\The Watcher"
#>
param(
    [string]$OutDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Read the app version (e.g. 0.1.0-test) so the distributable ZIP is labelled.
$Version = "0.0.0"
$InitPy  = Join-Path $ProjectRoot "app\__init__.py"
if (Test-Path $InitPy) {
    $m = Select-String -Path $InitPy -Pattern '__version__\s*=\s*"([^"]+)"' -ErrorAction SilentlyContinue
    if ($m) { $Version = $m.Matches[0].Groups[1].Value }
}

# Paths used during build - must be comma-free so Qt/PyInstaller hooks work.
$CleanVenv    = "C:\TW_Venv"
$JunctionPath = "C:\TW_Build"

Write-Host "=== The Watcher Build ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"

# ---------------------------------------------------------------------------
# Step 1: Create a comma-free venv for PyInstaller
# Qt's QLibraryInfo.path() breaks when the venv path contains a comma, which
# causes the hook-PySide6.QtNetwork.py hook to raise:
#   "Qt plugin directory '...' does not exist!"
# Using a clean-path venv avoids this entirely.
# ---------------------------------------------------------------------------
$CleanPip        = "$CleanVenv\Scripts\pip.exe"
$CleanPyInstaller = "$CleanVenv\Scripts\pyinstaller.exe"

$NeedsVenvSetup = -not (Test-Path $CleanPyInstaller)
if ($NeedsVenvSetup) {
    Write-Host "Creating clean build venv at $CleanVenv ..." -ForegroundColor Yellow
    if (Test-Path $CleanVenv) { Remove-Item -Recurse -Force $CleanVenv }
    python -m venv $CleanVenv
    Write-Host "Installing packages into clean venv..." -ForegroundColor Yellow
    & $CleanPip install --upgrade pip --quiet
    & $CleanPip install `
        "PySide6==6.11.0" `
        "screeninfo==0.8.1" `
        "psutil==7.2.2" `
        "loguru==0.7.3" `
        "python-dotenv==1.2.2" `
        "pydantic==2.13.3" `
        "pyinstaller==6.20.0" `
        "pyinstaller-hooks-contrib==2026.4" `
        --quiet
    Write-Host "Clean venv ready." -ForegroundColor Green
} else {
    Write-Host "Using existing clean build venv at $CleanVenv" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Step 2: Create junction so PyInstaller sees the project at a comma-free path
# ---------------------------------------------------------------------------
if (Test-Path $JunctionPath) {
    cmd /c rmdir "$JunctionPath" | Out-Null
}
cmd /c mklink /J "$JunctionPath" "$ProjectRoot" | Out-Null
Write-Host "Junction: $JunctionPath -> $ProjectRoot" -ForegroundColor Gray

$BuildRoot = $JunctionPath
$BuildSpec = Join-Path $JunctionPath "installer\The Watcher.spec"

# ---------------------------------------------------------------------------
# Step 3: Run PyInstaller
# ---------------------------------------------------------------------------
Write-Host "Running PyInstaller..." -ForegroundColor Cyan

# Manually remove previous build/dist folders; PyInstaller's internal rmtree
# cannot handle reparse points created by the junction build (PermissionError
# on nested directories like pydantic dist-info\licenses).
$OldBuild = Join-Path $ProjectRoot "build\The Watcher"
if (Test-Path $OldBuild) {
    cmd /c rmdir /S /Q "$OldBuild" 2>&1 | Out-Null
    if (Test-Path $OldBuild) { Remove-Item -Recurse -Force $OldBuild -ErrorAction SilentlyContinue }
    Write-Host "Cleaned old build folder." -ForegroundColor Gray
}
$OldDist = Join-Path $ProjectRoot "dist\The Watcher"
if (Test-Path $OldDist) {
    cmd /c rmdir /S /Q "$OldDist" 2>&1 | Out-Null
    if (Test-Path $OldDist) { Remove-Item -Recurse -Force $OldDist -ErrorAction SilentlyContinue }
    Write-Host "Cleaned old dist folder." -ForegroundColor Gray
}

Push-Location $BuildRoot
try {
    $PyInstallerArgs = @(
        "--noconfirm",
        "--distpath", "dist",
        "--workpath", "build",
        $BuildSpec
    )
    & $CleanPyInstaller @PyInstallerArgs
} finally {
    Pop-Location
}

# The junction IS the project root, so PyInstaller already wrote dist to
# ProjectRoot\dist\The Watcher. No copy needed - just remove the junction.
cmd /c rmdir "$JunctionPath" | Out-Null
Write-Host "Junction removed." -ForegroundColor Gray

$DistDir = Join-Path $ProjectRoot "dist\The Watcher"
if (-not (Test-Path $DistDir)) {
    Write-Error "Build failed - dist\The Watcher not found."
}
Write-Host "Build complete: $DistDir" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Copy .env.example as default .env (user-editable config)
# ---------------------------------------------------------------------------
$EnvExample = Join-Path $ProjectRoot ".env.example"
$EnvDest    = Join-Path $DistDir ".env"
if ((Test-Path $EnvExample) -and -not (Test-Path $EnvDest)) {
    Copy-Item $EnvExample $EnvDest
    Write-Host "Copied .env.example to dist\The Watcher\.env"
}

# ---------------------------------------------------------------------------
# Copy installer scripts into the dist folder for end-user installation
# ---------------------------------------------------------------------------
$InstallScript     = Join-Path $ScriptDir "install.ps1"
$InstallScriptDest = Join-Path $DistDir "install.ps1"
if (Test-Path $InstallScript) {
    Copy-Item $InstallScript $InstallScriptDest -Force
    Write-Host "Copied install.ps1 to dist\The Watcher\"
}

# Setup.bat - double-click installer for users unfamiliar with PowerShell.
# It calls install.ps1 with -ExecutionPolicy Bypass so it works on any PC.
$SetupBat     = Join-Path $ScriptDir "Setup.bat"
$SetupBatDest = Join-Path $DistDir "Setup.bat"
if (Test-Path $SetupBat) {
    Copy-Item $SetupBat $SetupBatDest -Force
    Write-Host "Copied Setup.bat to dist\The Watcher\"
}

# ---------------------------------------------------------------------------
# Optional: copy to custom output directory
# ---------------------------------------------------------------------------
if ($OutDir -ne "") {
    Write-Host "Copying to $OutDir ..." -ForegroundColor Cyan
    if (-not (Test-Path $OutDir)) {
        New-Item -ItemType Directory -Path $OutDir | Out-Null
    }
    Copy-Item -Recurse -Force $DistDir $OutDir
    Write-Host "Copied to $OutDir" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Create distributable ZIP (contains Setup.bat + install.ps1 + exe)
# ---------------------------------------------------------------------------
$ZipPath = Join-Path $ProjectRoot "dist\The Watcher-$Version.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

# Retry the compression: the dist folder lives inside OneDrive, which (along
# with Windows Defender) transiently locks just-written files such as
# _internal\base_library.zip. Compress-Archive raises a non-terminating error
# on the lock, so without a retry the build would falsely report success
# without producing the ZIP.
$ZipOk = $false
for ($i = 1; $i -le 4 -and -not $ZipOk; $i++) {
    try {
        Compress-Archive -Path $DistDir -DestinationPath $ZipPath -Force -ErrorAction Stop
        $ZipOk = $true
    } catch {
        Write-Warning "ZIP attempt $i failed (likely OneDrive/Defender lock): $($_.Exception.Message)"
        if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 3
    }
}
if (-not $ZipOk) {
    Write-Error "Failed to create $ZipPath after 4 attempts (file lock). Pause OneDrive sync on dist\ and re-run."
}
Write-Host "Distribution package: $ZipPath" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Optional: build a proper Windows installer using Inno Setup 6
# Install Inno Setup from https://jrsoftware.org/isdl.php  or:
#   winget install --id JRSoftware.InnoSetup
# ---------------------------------------------------------------------------
$IsccCandidates = @(
    "iscc.exe",   # on PATH
    "C:\Program Files (x86)\Inno Setup 6\iscc.exe",
    "C:\Program Files\Inno Setup 6\iscc.exe"
)
$IsccPath = $null
foreach ($c in $IsccCandidates) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $IsccPath = $c; break }
    if (Test-Path  $c)                                { $IsccPath = $c; break }
}

$IssScript = Join-Path $ScriptDir "The Watcher.iss"
if ($IsccPath -and (Test-Path $IssScript)) {
    Write-Host "Building Inno Setup installer..." -ForegroundColor Cyan
    Push-Location $ProjectRoot
    try {
        & $IsccPath $IssScript
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Inno Setup installer: dist\Setup-The Watcher.exe" -ForegroundColor Green
        } else {
            Write-Warning "Inno Setup exited with code $LASTEXITCODE - installer not created."
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "(Inno Setup not found - skipping .exe installer. Install it with: winget install --id JRSoftware.InnoSetup)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "=== Build finished (v$Version) ===" -ForegroundColor Cyan
Write-Host "  Executable     : dist\The Watcher\The Watcher.exe"
Write-Host "  ZIP (portable) : dist\The Watcher-$Version.zip"
if (Test-Path (Join-Path $ProjectRoot "dist\Setup-The Watcher.exe")) {
    Write-Host "  Installer      : dist\Setup-The Watcher.exe" -ForegroundColor Green
}
Write-Host ""
Write-Host "  Quick install (double-click): dist\The Watcher\Setup.bat"
Write-Host "  Or via PowerShell           : dist\The Watcher\install.ps1" -ForegroundColor Yellow
