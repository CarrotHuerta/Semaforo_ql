#ifndef AppVersion
  #error Build with scripts/Build-Windows.ps1
#endif
#if Ver != Int(RequiredCompilerVersion)
  #error Incorrect Inno Setup compiler version
#endif
#ifndef Production
  #define Production 0
#endif
[Setup]
AppId={{48F91B83-1464-47F8-A13B-B2A64372D6D1}
AppName=Semáforo IA
AppVersion={#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL=https://github.com/CarrotHuerta/Semaforo_ql
DefaultDirName={localappdata}\Programs\SemaforoIA
DefaultGroupName=Semáforo IA
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
UninstallDisplayIcon={app}\SemaforoIA.exe
SetupIconFile={#IconFile}
OutputDir={#OutputRoot}
OutputBaseFilename=SemaforoIA-{#AppVersion}-windows-x64{#ChannelSuffix}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
AppMutex=Local\SemaforoIA.GUI,Local\SemaforoIA.CLI,Local\SemaforoIA.Server
Uninstallable=yes
#if Int(Production)
SignedUninstaller=yes
SignedUninstallerDir={#SignedUninstallerRoot}
SignTool=semaforo
#else
SignedUninstaller=no
#endif

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "{#BundleRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Semáforo IA"; Filename: "{app}\SemaforoIA.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Semáforo IA"; Filename: "{app}\SemaforoIA.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\SemaforoIA.exe"; Description: "Abrir Semáforo IA"; Flags: nowait postinstall skipifsilent

[Code]
var PurgeData: Boolean;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if FileExists(ExpandConstant('{app}\portable.flag')) or DirExists(ExpandConstant('{app}\userdata')) then
    Result := 'Esta carpeta contiene una distribución portable o datos. Elija otra carpeta; no se sobrescribirán.';
end;

function GetFileAttributesW(Name: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function SafeTree(Path: String): Boolean;
var Rec: TFindRec; Child: String;
begin
  Result := False;
  if (GetFileAttributesW(Path) and $400) <> 0 then exit;
  if FindFirst(AddBackslash(Path) + '*', Rec) then begin
    try
      repeat
        if (Rec.Name <> '.') and (Rec.Name <> '..') then begin
          if (Rec.Attributes and $400) <> 0 then exit;
          if (Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then begin
            Child := AddBackslash(Path) + Rec.Name;
            if not SafeTree(Child) then exit;
          end;
        end;
      until not FindNext(Rec);
    finally FindClose(Rec); end;
  end;
  Result := True;
end;

function InitializeUninstall(): Boolean;
var Form: TSetupForm; Check: TNewCheckBox; Accept, Cancel: TNewButton;
begin
  PurgeData := ExpandConstant('{param:PURGEUSERDATA|0}') = '1';
  Result := True;
  if UninstallSilent then exit;
  Form := CreateCustomForm(ScaleX(480), ScaleY(150), False, False);
  try
    Form.Caption := 'Desinstalar Semáforo IA';
    Check := TNewCheckBox.Create(Form); Check.Parent := Form;
    Check.Left := ScaleX(20); Check.Top := ScaleY(24);
    Check.Width := ScaleX(440); Check.Height := ScaleY(48);
    Check.Caption := 'Eliminar también los datos locales de esta cuenta (irreversible)';
    Check.Checked := False;
    Accept := TNewButton.Create(Form); Accept.Parent := Form;
    Accept.Caption := 'Desinstalar'; Accept.ModalResult := mrOk;
    Accept.Left := ScaleX(250); Accept.Top := ScaleY(100); Accept.Width := ScaleX(100);
    Cancel := TNewButton.Create(Form); Cancel.Parent := Form;
    Cancel.Caption := 'Cancelar'; Cancel.ModalResult := mrCancel;
    Cancel.Left := ScaleX(360); Cancel.Top := ScaleY(100); Cancel.Width := ScaleX(100);
    Result := Form.ShowModal = mrOk;
    PurgeData := Result and Check.Checked;
  finally Form.Free; end;
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
var Root, Expected: String; Marker: AnsiString;
begin
  if (Step = usPostUninstall) and PurgeData then begin
    Expected := ExpandFileName(ExpandConstant('{localappdata}\SemaforoIA'));
    Root := ExpandFileName(Expected);
    if (CompareText(Root, Expected) <> 0) or (Root = ExpandFileName(ExpandConstant('{app}'))) then
      RaiseException('Ruta de datos no válida. Se conservaron los datos.');
    if not DirExists(Root) then exit;
    if not LoadStringFromFile(AddBackslash(Root) + '.semaforo-userdata', Marker) then
      RaiseException('Falta el marcador de propiedad. Se conservaron los datos.');
    if (Trim(Marker) <> 'SemaforoIA') or not SafeTree(Root) then
      RaiseException('Ruta o enlaces no seguros. Se conservaron los datos.');
    if not DelTree(Root, True, True, True) then
      RaiseException('No se pudieron eliminar todos los datos; revise permisos.');
  end;
end;
