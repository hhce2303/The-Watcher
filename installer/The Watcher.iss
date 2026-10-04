; ===========================================================================
; The Watcher — Inno Setup 6 installer script
;
; Requirements: Inno Setup 6  https://jrsoftware.org/isdl.php
;
; Build (from the repository root):
;   iscc installer\The Watcher.iss
;
; Output: dist\Setup-The Watcher.exe
; ===========================================================================

#define AppName      "The Watcher"
#ifndef AppVersion
  ; build.ps1 passes /DAppVersion=<app.__version__>
  #define AppVersion "0.1.0"
#endif
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
Name: "{autoprograms}\Configurar firewall de {#AppName}"; \
    Filename: "{app}\Configurar firewall.cmd"; \
    WorkingDir: "{app}"; \
    Comment: "Crea o corrige las reglas de firewall (pide administrador)"
Name: "{autoprograms}\Datos de enrolamiento de {#AppName}"; \
    Filename: "{app}\Datos de enrolamiento.cmd"; \
    WorkingDir: "{app}"; \
    Comment: "Muestra y copia los datos públicos para registrar la estación en Daily"

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

procedure ConfigureLiveViewFirewall();
var
  ResultCode: Integer;
begin
  // This is the only privileged operation.  ShellExec('runas') may ask for an
  // administrator credential, but the application itself has already been
  // installed in the original interactive user's LocalAppData directory.
  // watcher-firewall.ps1 resolves the exe from its own folder ({app}), so an
  // IT credential does not redirect it to another profile.  Exit code 2 means
  // rules were created but a warning (Public network, Block rule) remains.
  if not ShellExec('runas', 'powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\watcher-firewall.ps1') + '" -Quiet',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode = 1) then
    MsgBox('The Watcher se instaló, pero no se crearon las reglas de firewall. Pida a IT ejecutar "Configurar firewall de The Watcher" desde el menú Inicio.', mbInformation, MB_OK)
  else if ResultCode = 2 then
    MsgBox('Reglas de firewall creadas, pero la red es Public o hay una regla que bloquea el puerto 8767. Ejecute "Configurar firewall de The Watcher" desde el menú Inicio para ver el detalle.', mbInformation, MB_OK);
end;

procedure TrustProvisionedCertificates();
var
  ResultCode: Integer;
  FindRec: TFindRec;
  TrustDir: String;
begin
  // Public CA certificates shipped by the TLS provisioning service in
  // certs\trust\*.pem.  Never imports a private key.
  TrustDir := ExpandConstant('{app}\certs\trust\');
  if FindFirst(TrustDir + '*.pem', FindRec) then
  begin
    try
      repeat
        Exec(ExpandConstant('{sys}\certutil.exe'), '-user -addstore Root "' + TrustDir + FindRec.Name + '"', '', SW_HIDE,
          ewWaitUntilTerminated, ResultCode);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    StopLegacyOperatorRuntime()
  else if CurStep = ssPostInstall then
  begin
    TrustProvisionedCertificates();
    ConfigureLiveViewFirewall();
  end;
end;
