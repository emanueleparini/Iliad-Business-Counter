; Installer di iliad counter.
;
;   ISCC.exe /DMyAppVersion=1.0.0 packaging\installer.iss
;
; Installa in %LOCALAPPDATA%\Programs: nessun UAC, nessun diritto di
; amministratore. Config e dati stanno in %LOCALAPPDATA%\iliad counter.

#define MyAppName "iliad counter"
#define MyAppPublisher "Emanuele Parini"
#define MyAppURL "https://github.com/emanueleparini/Iliad-Business-Counter"
#define MyAppExeName "iliad-counter.exe"

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{314067D3-1A59-43F1-86F6-1AA4C59A5C53}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=iliad-counter-setup-{#MyAppVersion}
SetupIconFile=..\assets\iliad.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
#ifdef Sign
; build.ps1 -Sign definisce lo strumento "artifactsigning" via ISCC /S
SignTool=artifactsigning
SignedUninstaller=yes
#endif

[Languages]
Name: "italiano"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startupicon"; Description: "Avvia iliad counter all'accesso a Windows"; GroupDescription: "Avvio automatico:"

[Files]
Source: "..\dist\iliad-counter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; il widget puo' creare da solo il collegamento di avvio automatico
Type: files; Name: "{userstartup}\{#MyAppName}.lnk"
