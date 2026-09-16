; ===========================================================================
; The Watcher — Inno Setup 6 installer script
;
; Requirements: Inno Setup 6  https://jrsoftware.org/isdl.php
;
; Build (from project/ directory):
;   iscc installer\The Watcher.iss
;
; Output: dist\Setup-The Watcher.exe
; ===========================================================================

#define AppName      "The Watcher"
#define AppVersion   "0.1.0-test"
#define AppPublisher "SIG Systems"
#define AppExeName   "The Watcher.exe"
#define AppURL       "https://sigsystems.com"
#ifndef SourceDir
  #define SourceDir "..\dist\The Watcher"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

; ---------------------------------------------------------------------------
[Setup]
; Unique app ID — regenerate with Tools > Generate GUID if you fork this app
AppId={{B4F2A1C3-9E5D-4F7B-8A6E-2D3C0F1E4B9A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

; Install to current user's LOCALAPPDATA — no elevation required
DefaultDirName={localappdata}\{#AppName}
DisableDirPage=yes
; Install the daemon and its per-user enrollment under the interactive Operator
; account.  Do not elevate the whole installer: otherwise {localappdata} is
; resolved as the administrator account supplied to UAC instead of csoperator.
PrivilegesRequired=lowest

; Start Menu group
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; Output
OutputDir={#OutputDir}
OutputBaseFilename=Setup-The Watcher
SetupIconFile=

; Compression
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Wizard appearance
WizardStyle=modern
WizardSizePercent=120

; Windows 10 or later required (Desktop Duplication API)
MinVersion=10.0

; ---------------------------------------------------------------------------
[Languages]
Name: "spanish";  MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english";  MessagesFile: "compiler:Default.isl"

; ---------------------------------------------------------------------------
[Messages]
spanish.BeveledLabel=Español
english.BeveledLabel=English

; Custom messages
spanish.WelcomeLabel1=Bienvenido al instalador de [name]
spanish.WelcomeLabel2=Este asistente instalará [name/ver] en su equipo.%n%nThe Watcher graba automáticamente su pantalla cuando ocurre un evento. FFmpeg ya está incluido, no necesita instalar nada más.%n%nHaga clic en Siguiente para continuar.
english.WelcomeLabel2=This wizard will install [name/ver] on your computer.%n%nThe Watcher automatically records your screen when an event occurs. FFmpeg is already bundled — no additional software needed.%n%nClick Next to continue.

; ---------------------------------------------------------------------------
[Tasks]
Name: "autostart"; \
    Description: "Iniciar automáticamente con Windows"; \
    GroupDescription: "Inicio de sesión:"; \
    Flags: unchecked

; ---------------------------------------------------------------------------
[Files]
; All files from the PyInstaller one-dir build (includes bundled ffmpeg)
Source: "{#SourceDir}\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; ---------------------------------------------------------------------------
[Icons]
; Start Menu only — no desktop shortcut
Name: "{autoprograms}\{#AppName}"; \
    Filename: "{app}\{#AppExeName}"; \
    Comment: "The Watcher - Grabación automática de pantalla"

; ---------------------------------------------------------------------------
[Registry]
; Operator deployment: start the daemon at Windows login.
Root: HKCU; \
    Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; \
    ValueName: "{#AppName}"; \
    ValueData: """{app}\{#AppExeName}"" --daemon"; \
    Flags: uninsdeletevalue

; ---------------------------------------------------------------------------
[Run]
; Offer to launch after install
Filename: "{app}\{#AppExeName}"; \
    Parameters: "--daemon"; \
    Description: "Iniciar {#AppName} ahora"; \
    Flags: nowait postinstall skipifsilent; \
    Check: IsLegacyInstall; \
    WorkingDir: "{app}"

; ---------------------------------------------------------------------------
[UninstallRun]
; Stop the app gracefully before uninstall
Filename: "taskkill.exe"; \
    Parameters: "/F /IM {#AppExeName}"; \
    Flags: runhidden waituntilterminated; \
    RunOnceId: "StopTheWatcher"
Filename: "schtasks.exe"; \
    Parameters: "/Delete /TN ""TheWatcher-OperatorWatchdog"" /F"; \
    Flags: runhidden waituntilterminated; \
    RunOnceId: "RemoveTheWatcherWatchdog"

[InstallDelete]
; Remove stale unpacked runtime files from a previous one-dir release. Clips
; and the persisted Operator identity are outside this target and preserved.
Type: filesandordirs; Name: "{app}\_internal"

; ---------------------------------------------------------------------------
[UninstallDelete]
; Remove recorded data directories created at runtime
; (only removes them if they are empty — won't delete user clips)
Type: dirifempty; Name: "{localappdata}\{#AppName}"

; ---------------------------------------------------------------------------
[Code]
var
  NasPathPage: TInputQueryWizardPage;

// Show a warning if the OS is older than Windows 10 (belt-and-suspenders,
// since MinVersion already blocks older versions at setup start).
function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  GetWindowsVersionEx(Version);
  if Version.Major < 10 then
  begin
    MsgBox(
      'The Watcher requiere Windows 10 o superior.' + #13#10 +
      'La instalación no puede continuar.',
      mbCriticalError, MB_OK
    );
    Result := False;
  end else
    Result := True;
end;

procedure StopLegacyOperatorRuntime();
var
  ResultCode: Integer;
begin
  // Cleanup is intentionally limited to our executable and watchdog. It does
  // not delete recordings or enrolment data.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "{#AppExeName}"', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\schtasks.exe'),
    '/Delete /TN "TheWatcher-OperatorWatchdog" /F', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
  RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
end;

procedure WriteOperatorProfile();
var
  ProfilePath: String;
  ProfileJson: String;
begin
  ProfilePath := ExpandConstant('{localappdata}\{#AppName}\user_config.json');
  ProfileJson :=
    '{' + #13#10 +
    '  "clips_dir": null,' + #13#10 +
    '  "selected_monitor_fingerprints": [],' + #13#10 +
    '  "driver": "auto",' + #13#10 +
    '  "codec": null,' + #13#10 +
    '  "autorecord": true,' + #13#10 +
    '  "it_ws_hosts": [],' + #13#10 +
    '  "role": "operator"' + #13#10 +
    '}';
  if not SaveStringToFile(ProfilePath, ProfileJson, False) then
    RaiseException('Could not write the Operator profile.');
end;

procedure ConfigureLiveViewFirewall();
var
  ResultCode: Integer;
begin
  // This is the only privileged operation.  ShellExec('runas') may ask for an
  // administrator credential, but the application itself has already been
  // installed in the original interactive user's LocalAppData directory.
  if not ShellExec('runas', ExpandConstant('{sys}\netsh.exe'),
    'advfirewall firewall add rule name=""The Watcher Live View"" dir=in action=allow protocol=TCP localport=8767 profile=private',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    MsgBox('The Watcher was installed for this user, but the LAN firewall rule was not added. Ask IT to allow TCP 8767 on the Private profile before using live supervision.', mbInformation, MB_OK);
end;

procedure SaveNasDestination();
var
  NasPath: String;
begin
  NasPath := Trim(NasPathPage.Values[0]);
  if not SaveStringToFile(ExpandConstant('{app}\operator-nas-path.txt'), NasPath, False) then
    RaiseException('Could not save the final clips NAS destination.');
end;

procedure InitializeOperatorProvisioning();
var
  ResultCode: Integer;
begin
  // The helper executes as the interactive Operator (this installer is
  // PrivilegesRequired=lowest).  It generates the device-local mkcert CA,
  // leaf TLS certificate, and runtime profile. No private material comes from
  // the IT workstation.
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\Initialize-WatcherOperator.ps1') +
    '" -InstallDir "' + ExpandConstant('{app}') + '"', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    RaiseException('The Watcher could not complete local certificate provisioning. The installation was not started.');
end;

procedure InitializeWizard();
begin
  NasPathPage := CreateInputQueryPage(
    wpSelectTasks,
    'Clips finales en NAS',
    'Seleccione la ruta de destino para los clips combinados',
    'The Watcher conserva segmentos y previews en el PC Operador. Solo los MP4 finales combinados se guardan en el NAS.'
  );
  NasPathPage.Add('Ruta UNC del NAS (requerida):', False);
  NasPathPage.Values[0] := '\\SIG-SLC-Storage\Storage3\';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  NasPath: String;
begin
  Result := True;
  if CurPageID = NasPathPage.ID then
  begin
    NasPath := Trim(NasPathPage.Values[0]);
    if (NasPath = '') or (Copy(NasPath, 1, 2) <> '\\') then
    begin
      MsgBox('Ingresa una ruta UNC valida para el NAS, por ejemplo \\SIG-SLC-Storage\Storage3\Operator 45.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function IsLegacyInstall(): Boolean;
begin
  // Provisioned installs are started by Initialize-WatcherOperator.ps1 so it
  // can export the destination-generated public enrollment key exactly once.
  Result := not FileExists(ExpandConstant('{app}\operator-provisioning.json'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    StopLegacyOperatorRuntime()
  else if CurStep = ssPostInstall then
  begin
    WriteOperatorProfile();
    if not IsLegacyInstall() then
    begin
      SaveNasDestination();
      InitializeOperatorProvisioning();
      if FileExists(ExpandConstant('{app}\live-view-enabled.flag')) then
        ConfigureLiveViewFirewall();
    end;
  end;
end;
