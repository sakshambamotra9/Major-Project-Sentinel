; Inno Setup Script for Sentinel Proctoring Platform
; Download Inno Setup from: https://jrsoftware.org/isdownload.php
; To build: Open this file in Inno Setup and click Build -> Compile (Ctrl+F9)

#define MyAppName "Sentinel Proctoring Platform"
#define MyAppVersion "1.0"
#define MyAppPublisher "Sentinel AI"
#define MyAppExeName "Sentinel_Proctoring.exe"
#define MyOutputDir "c:\8th SEM\Major project\dist"

[Setup]
; Unique AppId for installers
AppId={{5D07C0A5-74F2-4889-ACBA-C6F4B7AE2899}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
; Force Administrator privileges during install (required to setup system hooks correctly)
PrivilegesRequired=admin
OutputDir={#MyOutputDir}
OutputBaseFilename=Sentinel_Proctoring_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Source directory of the PyInstaller build
Source: "c:\8th SEM\Major project\dist\Sentinel_Proctoring\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: runascurrentuser nowait postinstall skipifsilent
