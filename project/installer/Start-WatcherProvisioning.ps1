<#
.SYNOPSIS
    Opens the lightweight IT-only provisioning console for The Watcher.

.DESCRIPTION
    This console deliberately creates a *provisioning request*, not a device
    key or certificate.  The request travels with the field setup and the
    destination Operator PC generates its Ed25519 device key and local TLS
    material there.  Keeping private material on that machine is essential:
    an IT workstation must never manufacture or retain an Operator's private
    identity.

    Current phase: collect and validate the station identity and emit a small,
    non-secret JSON request.  The following installer phase will consume this
    schema, create the keypair locally, and enrol only the public key.

.EXAMPLE
    .\Start-WatcherProvisioning.ps1
#>
[CmdletBinding()]
param(
    [string]$OutputDirectory = 'C:\Watcher-Provisioning'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Test-StationNumber {
    param([string]$Value)
    return $Value -match '^[1-9][0-9]{0,8}$'
}

function Test-StationId {
    param([string]$Value)
    $parsed = 0L
    return [long]::TryParse($Value, [ref]$parsed) -and $parsed -ge 1 -and $parsed -le 2147483647
}

function Test-Endpoint {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
    $ip = $null
    if ([System.Net.IPAddress]::TryParse($Value, [ref]$ip)) { return $true }
    return $Value -match '^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$'
}

function Get-MkcertExecutable {
    # Winget does not reliably refresh PATH in a PowerShell process that was
    # already open when mkcert was installed. Check the package location too.
    $command = Get-Command 'mkcert.exe' -ErrorAction SilentlyContinue
    if ($command -and (Test-Path -LiteralPath $command.Source -PathType Leaf)) {
        return $command.Source
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

function New-ProvisioningRequest {
    param(
        [Parameter(Mandatory)][int]$StationId,
        [Parameter(Mandatory)][string]$StationNumber,
        [string]$Endpoint,
        [Parameter(Mandatory)][string]$Directory
    )

    $safeStationNumber = $StationNumber.Trim()
    $request = [ordered]@{
        schema_version = 1
        request_type = 'operator_daemon_provisioning'
        created_at_utc = [DateTime]::UtcNow.ToString('o')
        station = [ordered]@{
            id_station = $StationId
            station_number = $safeStationNumber
            endpoint_hint = $Endpoint.Trim()
        }
        device_identity = [ordered]@{
            generation = 'destination_setup'
            algorithm = 'Ed25519'
            private_key_export = $false
            enrollment = 'public_key_only'
        }
        local_tls = [ordered]@{
            generation = 'destination_setup'
            bind = @('127.0.0.1', '::1')
        }
    }

    # Requests are implementation detail; the IT user chooses the provisioning
    # root and receives the finished Setup in its packages/ subdirectory.
    $fullDirectory = Join-Path ([IO.Path]::GetFullPath($Directory)) '.requests'
    [IO.Directory]::CreateDirectory($fullDirectory) | Out-Null
    $fileName = 'watcher-provisioning-station-{0}-id-{1}.json' -f $safeStationNumber, $StationId
    $path = Join-Path $fullDirectory $fileName
    if (Test-Path -LiteralPath $path) {
        $stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
        $path = Join-Path $fullDirectory ('watcher-provisioning-station-{0}-id-{1}-{2}.json' -f $safeStationNumber, $StationId, $stamp)
    }

    $json = $request | ConvertTo-Json -Depth 5
    [IO.File]::WriteAllText($path, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    return $path
}

$form = [System.Windows.Forms.Form]::new()
$form.Text = 'The Watcher - Provision de estacion'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = [System.Drawing.Size]::new(650, 490)
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.Font = [System.Drawing.Font]::new('Segoe UI', 10)

$title = [System.Windows.Forms.Label]::new()
$title.Text = 'Preparar instalacion de The Watcher'
$title.Font = [System.Drawing.Font]::new('Segoe UI Semibold', 16)
$title.Location = [System.Drawing.Point]::new(24, 22)
$title.AutoSize = $true
$form.Controls.Add($title)

$intro = [System.Windows.Forms.Label]::new()
$intro.Text = 'Uso exclusivo de IT. Esta pantalla crea una solicitud segura para el setup del PC Operador.'
$intro.Location = [System.Drawing.Point]::new(26, 58)
$intro.Size = [System.Drawing.Size]::new(595, 42)
$intro.ForeColor = [System.Drawing.Color]::FromArgb(65, 65, 65)
$form.Controls.Add($intro)

function Add-Field {
    param([string]$Caption, [int]$Top, [string]$Help = '')
    $label = [System.Windows.Forms.Label]::new()
    $label.Text = $Caption
    $label.Location = [System.Drawing.Point]::new(28, $Top)
    $label.AutoSize = $true
    $form.Controls.Add($label)

    $box = [System.Windows.Forms.TextBox]::new()
    $box.Location = [System.Drawing.Point]::new(250, $Top - 4)
    $box.Size = [System.Drawing.Size]::new(365, 28)
    $form.Controls.Add($box)

    if ($Help) {
        $hint = [System.Windows.Forms.Label]::new()
        $hint.Text = $Help
        $hint.Location = [System.Drawing.Point]::new(250, $Top + 29)
        $hint.Size = [System.Drawing.Size]::new(365, 20)
        $hint.Font = [System.Drawing.Font]::new('Segoe UI', 8.5)
        $hint.ForeColor = [System.Drawing.Color]::FromArgb(95, 95, 95)
        $form.Controls.Add($hint)
    }
    return $box
}

$stationIdBox = Add-Field 'ID de estacion *' 120 'Identificador numerico existente en Daily.'
$stationNumberBox = Add-Field 'Numero de estacion *' 180 'Ejemplo: 30. Este valor se muestra a supervisores y operadores.'
$endpointBox = Add-Field 'Host o IP LAN (opcional)' 240 'Se conserva como pista para el setup; no se usa para generar llaves en este PC.'
$outputBox = Add-Field 'Carpeta de salida' 300 'El instalador final se guarda en packages. La solicitud se administra internamente.'
$outputBox.Text = $OutputDirectory

$status = [System.Windows.Forms.Label]::new()
$status.Location = [System.Drawing.Point]::new(28, 352)
$status.Size = [System.Drawing.Size]::new(585, 39)
$status.ForeColor = [System.Drawing.Color]::FromArgb(95, 95, 95)
$status.Text = 'La clave Ed25519 y el certificado TLS se crearan localmente al ejecutar Setup en el PC Operador.'
$form.Controls.Add($status)

$create = [System.Windows.Forms.Button]::new()
$create.Text = 'Crear Setup de esta estacion'
$create.Location = [System.Drawing.Point]::new(365, 440)
$create.Size = [System.Drawing.Size]::new(250, 34)
$create.BackColor = [System.Drawing.Color]::FromArgb(0, 120, 212)
$create.ForeColor = [System.Drawing.Color]::White
$create.FlatStyle = 'Flat'
$form.Controls.Add($create)

$progress = [System.Windows.Forms.ProgressBar]::new()
$progress.Location = [System.Drawing.Point]::new(28, 414)
$progress.Size = [System.Drawing.Size]::new(320, 12)
$progress.Visible = $false
$form.Controls.Add($progress)

$openFolder = [System.Windows.Forms.Button]::new()
$openFolder.Text = 'Abrir carpeta'
$openFolder.Location = [System.Drawing.Point]::new(28, 440)
$openFolder.Size = [System.Drawing.Size]::new(150, 34)
$openFolder.Visible = $false
$form.Controls.Add($openFolder)

$script:setupPackageDir = ''
$openFolder.Add_Click({
    if ($script:setupPackageDir -and (Test-Path -LiteralPath $script:setupPackageDir)) {
        Start-Process -FilePath 'explorer.exe' -ArgumentList $script:setupPackageDir
    }
})

$create.Add_Click({
    $stationId = $stationIdBox.Text.Trim()
    $stationNumber = $stationNumberBox.Text.Trim()
    $endpoint = $endpointBox.Text.Trim()
    $directory = $outputBox.Text.Trim()

    if (-not (Test-StationId $stationId)) {
        [System.Windows.Forms.MessageBox]::Show('Ingresa un ID de estacion numerico valido.', 'Dato requerido', 'OK', 'Warning') | Out-Null
        $stationIdBox.Focus(); return
    }
    if (-not (Test-StationNumber $stationNumber)) {
        [System.Windows.Forms.MessageBox]::Show('Ingresa un numero de estacion positivo, por ejemplo 30.', 'Dato requerido', 'OK', 'Warning') | Out-Null
        $stationNumberBox.Focus(); return
    }
    if (-not (Test-Endpoint $endpoint)) {
        [System.Windows.Forms.MessageBox]::Show('El host o IP LAN no tiene un formato valido.', 'Revisa el host', 'OK', 'Warning') | Out-Null
        $endpointBox.Focus(); return
    }
    if ([string]::IsNullOrWhiteSpace($directory)) {
        [System.Windows.Forms.MessageBox]::Show('Selecciona una carpeta de salida.', 'Dato requerido', 'OK', 'Warning') | Out-Null
        $outputBox.Focus(); return
    }

    try {
        $path = New-ProvisioningRequest -StationId ([int]$stationId) -StationNumber $stationNumber -Endpoint $endpoint -Directory $directory
        $builder = Join-Path $PSScriptRoot 'New-OperatorSetupPackage.ps1'
        $mkcert = Get-MkcertExecutable
        if (-not $mkcert) {
            $status.ForeColor = [System.Drawing.Color]::FromArgb(180, 90, 0)
            $status.Text = 'No se puede generar el Setup porque mkcert no esta disponible en este PC de IT.'
            [System.Windows.Forms.MessageBox]::Show(
                "Este PC de IT necesita mkcert para incluirlo en el Setup.`n`nInstalalo una sola vez con:`nwinget install --id FiloSottile.mkcert -e",
                'mkcert requerido', 'OK', 'Warning'
            ) | Out-Null
            return
        }
        $packageDir = Join-Path $directory (Join-Path 'packages' ("station-{0}-id-{1}" -f $stationNumber, $stationId))
        $script:setupPackageDir = $packageDir
        $openFolder.Visible = $false
        $create.Enabled = $false
        $stationIdBox.Enabled = $false
        $stationNumberBox.Enabled = $false
        $endpointBox.Enabled = $false
        $outputBox.Enabled = $false
        $progress.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
        $progress.Visible = $true
        $status.ForeColor = [System.Drawing.Color]::FromArgb(0, 90, 160)
        $status.Text = 'Generando el instalador. Esto puede tardar varios minutos...'

        $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -ProvisioningRequest "{1}" -OutDir "{2}" -MkcertPath "{3}"' -f $builder, $path, $packageDir, $mkcert
        $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
        $processInfo.FileName = 'powershell.exe'
        $processInfo.Arguments = $arguments
        $processInfo.WorkingDirectory = $PSScriptRoot
        $processInfo.UseShellExecute = $false
        $processInfo.CreateNoWindow = $true
        $script:setupBuildProcess = [System.Diagnostics.Process]::Start($processInfo)

        # Event handlers execute in their own scope. Keep the timer in script
        # state instead of closing over a local variable (StrictMode otherwise
        # raises "Variable '$poll' has not been set" on the first tick).
        $script:setupBuildTimer = [System.Windows.Forms.Timer]::new()
        $script:setupBuildTimer.Interval = 500
        $script:setupBuildTimer.Add_Tick({
            if (-not $script:setupBuildProcess.HasExited) { return }
            $script:setupBuildTimer.Stop()
            $progress.Visible = $false
            $create.Enabled = $true
            $stationIdBox.Enabled = $true
            $stationNumberBox.Enabled = $true
            $endpointBox.Enabled = $true
            $outputBox.Enabled = $true
            $setup = Join-Path $script:setupPackageDir 'Setup-The Watcher.exe'
            if ($script:setupBuildProcess.ExitCode -eq 0 -and (Test-Path -LiteralPath $setup -PathType Leaf)) {
                $status.ForeColor = [System.Drawing.Color]::FromArgb(0, 112, 60)
                $status.Text = "Instalador listo: $setup"
                $openFolder.Visible = $true
                [System.Windows.Forms.MessageBox]::Show("El Setup esta listo para compartir con el Operador.`n`n$setup", 'Setup listo', 'OK', 'Information') | Out-Null
            } else {
                $status.ForeColor = [System.Drawing.Color]::FromArgb(180, 30, 30)
                $status.Text = 'No se pudo generar el Setup. Revisa que Inno Setup este instalado y vuelve a intentarlo.'
                [System.Windows.Forms.MessageBox]::Show($status.Text, 'Error de build', 'OK', 'Error') | Out-Null
            }
            $script:setupBuildTimer.Dispose()
            $script:setupBuildTimer = $null
        })
        $script:setupBuildTimer.Start()
    } catch {
        $status.ForeColor = [System.Drawing.Color]::FromArgb(180, 30, 30)
        $status.Text = "No se pudo crear la solicitud: $($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show($status.Text, 'Error de provision', 'OK', 'Error') | Out-Null
    }
})

[void]$form.ShowDialog()
