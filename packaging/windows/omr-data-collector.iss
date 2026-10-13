; Inno Setup script: wraps PyInstaller's dist\omr-data-collector\ in a
; Setup.exe with a Start menu entry and an uninstaller. Run from the repository
; root after PyInstaller:
;
;   iscc /DAppVersion=<version> packaging\windows\omr-data-collector.iss
;
; Writes dist\OMR-Data-Collector-<version>-Windows-Setup.exe. It installs for
; the current user without asking for an administrator, unless they choose all
; users. People's data isn't in the install folder (it's in their AppData), so
; upgrading or uninstalling leaves it alone.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "OMR Data Collector"
#define AppExe "omr-data-collector.exe"

[Setup]
; Never change: Windows uses it to recognise upgrades of the same app.
AppId={{B003C4CE-9EA4-4F6D-A1DA-0B0E8F720CC0}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Michael Stewart
AppPublisherURL=https://github.com/mstewart14/omr-data-collector
AppSupportURL=https://github.com/mstewart14/omr-data-collector/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=OMR-Data-Collector-{#AppVersion}-Windows-Setup
SetupIconFile=..\icons\omr-data-collector.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; An upgrade replaces the bundled libraries outright, so none are left over
; from the version before.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\omr-data-collector\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
