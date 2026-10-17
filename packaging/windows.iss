#ifndef AppVersion
  #error "Build with scripts/build.py to derive the Git version"
#endif
#ifndef AppNumericVersion
  #error "Build with scripts/build.py to derive the numeric version"
#endif
[Setup]
AppId={{F617DE08-604C-4661-94E5-A5318BBD2E8C}
AppName=PhotoCraft
AppVersion={#AppVersion}
VersionInfoVersion={#AppNumericVersion}
AppPublisher=PhotoCraft
DefaultDirName={localappdata}\Programs\PhotoCraft
DefaultGroupName=PhotoCraft
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\artifacts
OutputBaseFilename=PhotoCraft-{#AppVersion}-windows-x64-setup
SetupIconFile=..\photocraft\assets\photocraft.ico
UninstallDisplayIcon={app}\PhotoCraft.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
CloseApplications=yes
AppMutex=PhotoCraftInstaller

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\PhotoCraft\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PhotoCraft"; Filename: "{app}\PhotoCraft.exe"; AppUserModelID: "PhotoCraft.Desktop"
Name: "{autodesktop}\PhotoCraft"; Filename: "{app}\PhotoCraft.exe"; Tasks: desktopicon; AppUserModelID: "PhotoCraft.Desktop"

[Run]
Filename: "{app}\PhotoCraft.exe"; Description: "Launch PhotoCraft"; Flags: nowait postinstall skipifsilent
