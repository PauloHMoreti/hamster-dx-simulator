; Instalador opcional com Inno Setup (https://jrsoftware.org/isinfo.php)
; 1) Rode build.bat   2) Abra este arquivo no Inno Setup e clique em Compile.
; Gera Output\HamsterDXSimulator-Setup.exe (instaladores Inno são bem aceitos
; pelos antivírus e o usuário ganha atalho no Menu Iniciar + desinstalador).

#define AppName "Hamster DX Simulator"
#define AppVersion "2.0.0"
#define AppExe "HamsterDXSimulator.exe"

[Setup]
AppId={{7C2F1E54-3A8B-4C61-9D6E-4B1F0A2C9E31}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\HamsterDXSimulator
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputBaseFilename=HamsterDXSimulator-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: unchecked

[Files]
Source: "..\dist\HamsterDXSimulator\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o {#AppName}"; Flags: nowait postinstall skipifsilent
