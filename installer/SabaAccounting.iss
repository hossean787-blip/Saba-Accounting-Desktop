#define MyAppName "Saba Accounting Desktop"
#define MyAppVersion "0.7.0-development"
#define MyAppPublisher "Saba Accounting Project"
#define MyAppExeName "SabaAccounting.exe"

[Setup]
AppId={{C6F6E365-3A08-4C94-A10B-C6B94412BA1E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\SabaAccounting
DefaultGroupName=حسابداری صبا
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SabaAccounting-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "ایجاد میانبر روی دسکتاپ"; GroupDescription: "میانبرها:"; Flags: unchecked

[Files]
Source: "..\dist\SabaAccounting.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\حسابداری صبا"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\حسابداری صبا"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "اجرای حسابداری صبا"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Customer databases live under %LOCALAPPDATA%\SabaAccounting and are
; intentionally never deleted by uninstall or upgrade.
Type: filesandordirs; Name: "{app}"
