<#
.SYNOPSIS
    Builds the The Watcher Windows executable (Milestone 8).

.DESCRIPTION
    1. Creates a clean build venv at C:\TW_Venv (comma-free path). This was
       originally a workaround for a Qt/PyInstaller path-parsing bug; QML/
       PySide6 are gone now (F3), but the repo path still contains a comma
       ("SIG Systems, Inc"), and other PyInstaller hooks have shown similar
       comma-sensitivity, so the clean-path venv/junction stays as a safe
       default rather than re-introducing that risk.
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

    # Required for a field-ready Operator installer. The profile and its
    # certs/ directory are embedded in the package.
    .\installer\build.ps1 -OperatorDeploymentConfig "C:\Provisioning\operator-deployment.env"
#>
param(
    [string]$OutDir = "",
    [string]$OperatorDeploymentConfig = "",
    [string]$OperatorProvisioningRequest = "",
    [string]$MkcertPath = "",
    [switch]$RequireInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($OperatorDeploymentConfig -and $OperatorProvisioningRequest) {
    throw 'Specify either OperatorDeploymentConfig or OperatorProvisioningRequest, not both.'
}
if ($OperatorProvisioningRequest -and -not $MkcertPath) {
    throw 'MkcertPath is required when building from an OperatorProvisioningRequest.'
}

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$StagingRoot = Join-Path $env:TEMP ("the-watcher-field-build-" + [guid]::NewGuid().ToString("N"))
$StagingDistRoot = Join-Path $StagingRoot "dist"
$StagingWorkRoot = Join-Path $StagingRoot "work"
New-Item -ItemType Directory -Force -Path $StagingDistRoot, $StagingWorkRoot | Out-Null

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
# Step 1: Create a comma-free venv for PyInstaller (see .DESCRIPTION above).
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
        "screeninfo==0.8.1" `
        "psutil==7.2.2" `
        "loguru==0.7.3" `
        "python-dotenv==1.2.2" `
        "pydantic==2.13.3" `
        "websockets==16.0" `
        "aiohttp>=3.11,<4" `
        "PyJWT[crypto]>=2.10,<3" `
        "pyinstaller==6.20.0" `
        "pyinstaller-hooks-contrib==2026.4" `
        --quiet
    Write-Host "Clean venv ready." -ForegroundColor Green
} else {
    Write-Host "Using existing clean build venv at $CleanVenv" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Step 1b: Build + install the native Rust segment engine into the clean venv.
# OPTIONAL / non-fatal — the app falls back to the FFmpeg segment compiler when
# the .pyd is absent (ENGINE_READY gate). Must run BEFORE PyInstaller so the
# .pyd lands in site-packages and the spec's hiddenimport can bundle it.
# ---------------------------------------------------------------------------
$CleanPython = "$CleanVenv\Scripts\python.exe"
$CrateDir    = Join-Path $ProjectRoot "native\watcher_segments"
if (Get-Command cargo -ErrorAction SilentlyContinue) {
    if (Test-Path $CrateDir) {
        Write-Host "Building native Rust engine (watcher_segments)..." -ForegroundColor Cyan
        & $CleanPip install --upgrade maturin --quiet
        $WheelOut = Join-Path $env:TEMP "tw_build_wheels"
        Push-Location $CrateDir
        try {
            # --interpreter (not `maturin develop`) so maturin targets THIS venv
            # and does not autodetect an unrelated one.
            & $CleanPython -m maturin build --release --interpreter $CleanPython --out $WheelOut
            if ($LASTEXITCODE -eq 0) {
                $Wheel = Get-ChildItem $WheelOut -Filter "watcher_segments-*.whl" -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime | Select-Object -Last 1
                if ($Wheel) {
                    & $CleanPip install --force-reinstall --no-deps $Wheel.FullName --quiet
                    Write-Host "Native Rust engine installed into clean venv." -ForegroundColor Green
                } else {
                    Write-Warning "Native engine wheel not found after build — using FFmpeg fallback."
                }
            } else {
                Write-Warning "Native engine build failed — the bundle will use the FFmpeg fallback."
            }
        } finally { Pop-Location }
    }
} else {
    Write-Warning "Rust toolchain (cargo) not found — building without the native engine (FFmpeg fallback)."
}

# ---------------------------------------------------------------------------
# Step 2: Create junction so PyInstaller sees the project at a comma-free path
# ---------------------------------------------------------------------------
$ExistingJunction = Get-Item -LiteralPath $JunctionPath -Force -ErrorAction SilentlyContinue
if ($ExistingJunction) {
    if ($ExistingJunction.LinkType -ne 'Junction' -or $ExistingJunction.Target -notcontains $ProjectRoot) {
        throw "Build junction path is occupied by an unexpected target: $JunctionPath"
    }
    Write-Host "Reusing build junction: $JunctionPath -> $ProjectRoot" -ForegroundColor Gray
} else {
    cmd /c mklink /J "$JunctionPath" "$ProjectRoot" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not create build junction: $JunctionPath" }
    Write-Host "Junction: $JunctionPath -> $ProjectRoot" -ForegroundColor Gray
}

$BuildRoot = $JunctionPath
$BuildSpec = Join-Path $JunctionPath "installer\The Watcher.spec"

# ---------------------------------------------------------------------------
# Step 3: Run PyInstaller
# ---------------------------------------------------------------------------
Write-Host "Running PyInstaller..." -ForegroundColor Cyan

# Manually remove previous build/dist folders; PyInstaller's internal rmtree
# cannot handle reparse points created by the junction build (PermissionError
# on nested directories like pydantic dist-info\licenses).
$OldBuild = Join-Path $StagingWorkRoot "The Watcher"
if (Test-Path $OldBuild) {
    cmd /c rmdir /S /Q "$OldBuild" 2>&1 | Out-Null
    if (Test-Path $OldBuild) { Remove-Item -Recurse -Force $OldBuild -ErrorAction SilentlyContinue }
    Write-Host "Cleaned old build folder." -ForegroundColor Gray
}
$OldDist = Join-Path $StagingDistRoot "The Watcher"
if (Test-Path $OldDist) {
    $OldDistEntries = @(Get-ChildItem -LiteralPath $OldDist -Force -ErrorAction SilentlyContinue)
    if ($OldDistEntries.Count -eq 0) {
        # OneDrive/Defender can retain a directory handle briefly even after
        # its contents are gone.  PyInstaller can safely reuse an empty dir.
        Write-Host "Reusing empty dist folder held by another process." -ForegroundColor Gray
    } else {
        # rmdir can finish removing all files but still return a sharing
        # violation while OneDrive/Defender releases the directory handle.
        # Treat an empty remainder as a reusable output directory instead of
        # failing the field-installer build.
        try { cmd /c rmdir /S /Q "$OldDist" 2>$null | Out-Null } catch { }
        $RemainingEntries = @(Get-ChildItem -LiteralPath $OldDist -Force -ErrorAction SilentlyContinue)
        if ((Test-Path $OldDist) -and $RemainingEntries.Count -gt 0) {
            throw "Could not clear previous distribution output: $OldDist"
        }
        Write-Host "Cleaned old dist folder." -ForegroundColor Gray
    }
}

Push-Location $BuildRoot
try {
    $PyInstallerArgs = @(
        "--noconfirm",
        "--distpath", $StagingDistRoot,
        "--workpath", $StagingWorkRoot,
        $BuildSpec
    )
    & $CleanPyInstaller @PyInstallerArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}

# The junction IS the project root, so PyInstaller already wrote dist to
# ProjectRoot\dist\The Watcher. No copy needed - just remove the junction.
cmd /c rmdir "$JunctionPath" | Out-Null
Write-Host "Junction removed." -ForegroundColor Gray

$DistDir = Join-Path $StagingDistRoot "The Watcher"
if (-not (Test-Path $DistDir)) {
    Write-Error "Build failed - dist\The Watcher not found."
}
Write-Host "Build complete: $DistDir" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Stage the runtime configuration. A normal development ZIP can retain the
# example file, but an external Operator installer is built only from a
# reviewed deployment profile. This prevents a package with localhost URLs,
# missing TLS material, or a missing Daily heartbeat endpoint from escaping.
# ---------------------------------------------------------------------------
$EnvExample = Join-Path $ProjectRoot ".env.example"
$EnvDest    = Join-Path $DistDir ".env"
if ($OperatorDeploymentConfig -ne "") {
    $ProfilePath = (Resolve-Path -LiteralPath $OperatorDeploymentConfig).Path
    $ProfileDir = Split-Path -Parent $ProfilePath
    $ProfileText = Get-Content -LiteralPath $ProfilePath -Raw -Encoding utf8
    $RequiredKeys = @(
        "LIVE_VIEW_ENABLED=true",
        "LIVE_VIEW_BIND_HOST=0.0.0.0",
        "LIVE_VIEW_ORIGIN=https://",
        "LIVE_VIEW_PARENT_ORIGIN=https://daily.sig.systems",
        "LIVE_VIEW_HEARTBEAT_URL=https://gbtmbuzlnxdjcexppomf.supabase.co/functions/v1/watcher-heartbeat",
        "LIVE_VIEW_ISSUER_KID=",
        "LIVE_VIEW_STATION_ID=",
        "LIVE_VIEW_CERT_FILE=",
        "LIVE_VIEW_KEY_FILE=",
        "LIVE_VIEW_ISSUER_PUBLIC_KEY_FILE="
    )
    foreach ($RequiredKey in $RequiredKeys) {
        if ($ProfileText -notmatch [regex]::Escape($RequiredKey)) {
            throw "Operator deployment profile is missing required setting: $RequiredKey"
        }
    }
    if ($ProfileText -match "REPLACE_WITH|OPERATOR-PC-DNS") {
        throw "Operator deployment profile still contains placeholders. Refusing to build an unusable installer."
    }
    foreach ($RelativeAsset in @("certs\\live-view.pem", "certs\\live-view-key.pem", "certs\\daily-issuer-public.pem", "certs\\watcher-test-rootCA.pem")) {
        $SourceAsset = Join-Path $ProfileDir $RelativeAsset
        if (-not (Test-Path -LiteralPath $SourceAsset -PathType Leaf)) {
            throw "Required Operator deployment asset is missing: $SourceAsset"
        }
        $DestinationAsset = Join-Path $DistDir $RelativeAsset
        $DestinationDir = Split-Path -Parent $DestinationAsset
        New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
        Copy-Item -LiteralPath $SourceAsset -Destination $DestinationAsset -Force
    }
    Copy-Item -LiteralPath $ProfilePath -Destination $EnvDest -Force
    Write-Host "Staged reviewed Operator deployment profile and TLS material." -ForegroundColor Green
} elseif ($OperatorProvisioningRequest -ne "") {
    # The request contains station metadata only.  Its certs and device key
    # are intentionally NOT generated on this IT workstation: the bundled
    # initializer runs mkcert on the destination Operator PC after install.
    $RequestPath = (Resolve-Path -LiteralPath $OperatorProvisioningRequest).Path
    $Request = Get-Content -LiteralPath $RequestPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($Request.schema_version -ne 1 -or $Request.request_type -ne 'operator_daemon_provisioning' -or
        -not $Request.station.id_station -or -not $Request.station.station_number) {
        throw 'Operator provisioning request is invalid or missing station identity.'
    }
    if (-not (Test-Path -LiteralPath $MkcertPath -PathType Leaf)) {
        throw "Bundled mkcert source was not found: $MkcertPath"
    }
    Copy-Item -LiteralPath $RequestPath -Destination (Join-Path $DistDir 'operator-provisioning.json') -Force
    $ToolsDir = Join-Path $DistDir 'tools'
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    Copy-Item -LiteralPath $MkcertPath -Destination (Join-Path $ToolsDir 'mkcert.exe') -Force
    foreach ($InstallerHelper in @('Initialize-WatcherOperator.ps1', 'Install-WatcherSupervisorTrust.ps1')) {
        $HelperPath = Join-Path $ScriptDir $InstallerHelper
        if (-not (Test-Path -LiteralPath $HelperPath -PathType Leaf)) {
            throw "Required installer helper is missing: $HelperPath"
        }
        Copy-Item -LiteralPath $HelperPath -Destination (Join-Path $DistDir $InstallerHelper) -Force
    }
    Write-Host 'Staged station request and destination-local certificate bootstrap.' -ForegroundColor Green
} elseif ((Test-Path $EnvExample) -and -not (Test-Path $EnvDest)) {
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
$ZipPath = Join-Path $StagingRoot "The Watcher-$Version.zip"
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
    "C:\Program Files\Inno Setup 6\iscc.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
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
        $IsccArgs = @("/DSourceDir=$DistDir")
        if ($OutDir -ne "") {
            New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
            $IsccArgs += "/DOutputDir=$OutDir"
        }
        $IsccArgs += $IssScript
        & $IsccPath @IsccArgs
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Inno Setup installer: dist\Setup-The Watcher.exe" -ForegroundColor Green
        } else {
            Write-Warning "Inno Setup exited with code $LASTEXITCODE - installer not created."
        }
    } finally {
        Pop-Location
    }
} else {
    if ($RequireInstaller) {
        throw "Inno Setup is required for this field installer. Install it with: winget install --id JRSoftware.InnoSetup -e"
    }
    Write-Host "(Inno Setup not found - skipping .exe installer. Install it with: winget install --id JRSoftware.InnoSetup)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "=== Build finished (v$Version) ===" -ForegroundColor Cyan
Write-Host "  Executable     : dist\The Watcher\The Watcher.exe"
Write-Host "  ZIP (portable) : dist\The Watcher-$Version.zip"
if ($OutDir -ne "" -and (Test-Path (Join-Path $OutDir "Setup-The Watcher.exe"))) {
    Write-Host "  Installer      : $(Join-Path $OutDir 'Setup-The Watcher.exe')" -ForegroundColor Green
} elseif (Test-Path (Join-Path $ProjectRoot "dist\Setup-The Watcher.exe")) {
    Write-Host "  Installer      : dist\Setup-The Watcher.exe" -ForegroundColor Green
}
Write-Host ""
Write-Host "  Quick install (double-click): dist\The Watcher\Setup.bat"
Write-Host "  Or via PowerShell           : dist\The Watcher\install.ps1" -ForegroundColor Yellow
