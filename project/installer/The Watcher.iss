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
#define SourceDir    "..\dist\The Watcher"

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
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Start Menu group
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; Output
OutputDir=..\dist
OutputBaseFilename=Setup-The Watcher
SetupIconFile=

; Compression
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Wizard appearance
WizardStyle=modern
WizardSizePercent=120
WizardImageFile=compiler:WizModernImage-IS.bmp
WizardSmallImageFile=compiler:WizModernSmallImage-IS.bmp

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
; Auto-start at Windows login (optional task)
Root: HKCU; \
    Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; \
    ValueName: "{#AppName}"; \
    ValueData: """{app}\{#AppExeName}"""; \
    Flags: uninsdeletevalue; \
    Tasks: autostart

; ---------------------------------------------------------------------------
[Run]
; Offer to launch after install
Filename: "{app}\{#AppExeName}"; \
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
