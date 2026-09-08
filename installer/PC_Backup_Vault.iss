#define MyAppName "PC Backup Vault"
#define MyAppVersion "1.9.3"
#define MyAppPublisher "KC"
#define MyAppExeName "PC_Backup_Vault.exe"

[Setup]
AppId={{A7BB4C0E-4A9B-4A92-8A73-8A5DF2A1B173}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PC Backup Vault
DefaultGroupName=PC Backup Vault
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=PC_Backup_Vault_1.9.3_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
SetupLogging=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\PC_Backup_Vault\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PC Backup Vault"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\PC Backup Vault"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Symbole:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "PC Backup Vault starten"; Flags: nowait postinstall skipifsilent
