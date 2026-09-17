; Prosperya Preview v0.1 — Inno Setup script.
; Per-user install (no admin), Start Menu + optional desktop shortcut,
; user data lives in %LOCALAPPDATA%\Prosperya and is NEVER touched by
; install/upgrade/uninstall.
;
; Compile: ISCC.exe installer\prosperya_preview.iss
; Output:  dist\Prosperya Preview Setup.exe

#define AppName "Prosperya Preview"
#define AppVersion "0.1.0"
#define AppPublisher "Prosperya"
#define AppExe "Prosperya.exe"

[Setup]
AppId={{8F3A2E71-4C2B-4E9A-9D51-7B3E5A1C6F02}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} v{#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\Prosperya
DefaultGroupName=Prosperya
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Prosperya Preview Setup
SetupIconFile=..\backend\scripts\prosperya.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea un'icona sul desktop"; GroupDescription: "Icone:"; Flags: unchecked

[Files]
Source: "..\backend\dist\Prosperya\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Prosperya"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{group}\Disinstalla Prosperya"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Prosperya"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Avvia Prosperya"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only remove files the installer put under {app}. User data in
; %LOCALAPPDATA%\Prosperya is outside {app} and is preserved by design.
Type: filesandordirs; Name: "{app}"
