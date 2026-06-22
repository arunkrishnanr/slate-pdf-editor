; Inno Setup script for Tirut PDF (Windows direct-distribution installer).
; Compile on Windows:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows_installer.iss
; Output:              dist\TirutPDF-Setup.exe
;
; CODE SIGNING (yours — needs your code-signing certificate):
;   Sign BOTH the app exe and the finished installer, e.g.:
;     signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
;       /f your_cert.pfx /p <pw> "dist\Tirut PDF.exe"
;     signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
;       /f your_cert.pfx /p <pw> "dist\TirutPDF-Setup.exe"
;   (Or configure Inno's [Setup] SignTool= directive to sign automatically.)

#define AppName "Tirut PDF"
#define AppVersion "1.0.0"
#define AppPublisher "Tirut"
#define AppExeName "Tirut PDF.exe"

[Setup]
; A stable, app-specific GUID. Keep this constant across versions so upgrades replace cleanly.
AppId={{8F3B2C5A-1D4E-4A7B-9C21-A1B2C3D4E5F6}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Tirut PDF
DefaultGroupName=Tirut PDF
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=dist
OutputBaseFilename=TirutPDF-Setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=slate\resources\icon.ico
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The PyInstaller one-folder build: Tirut PDF.exe + its DLLs + the bundled,
; self-contained Tesseract under vendor\. Package the whole folder into {app}.
Source: "dist\Tirut PDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Tirut PDF"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall Tirut PDF"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Tirut PDF"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Tirut PDF"; Flags: nowait postinstall skipifsilent
