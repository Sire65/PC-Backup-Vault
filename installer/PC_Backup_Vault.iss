#define MyAppName "PC Backup Vault"
#define MyAppVersion "1.8.0"
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
OutputBaseFilename=PC_Backup_Vault_1.8.0_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UsePreviousAppDir=yes
UninstallDisplayName=PC Backup Vault
UninstallDisplayIcon={app}\PC_Backup_Vault.exe
SetupLogging=yes
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Symbole:"; Flags: checkedonce

[Files]
Source: "..\dist\PC_Backup_Vault\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\PC Backup Vault"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\PC Backup Vault"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: WizardSilent
Filename: "{app}\{#MyAppExeName}"; Description: "PC Backup Vault jetzt starten"; Flags: nowait postinstall skipifsilent
