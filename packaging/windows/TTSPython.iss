; The Windows installer. packaging/build.py --installer passes the defines below.
; It installs for the current user without administrator rights. Settings, voices and models
; live in the user's AppData folders. Installing never touches them, and uninstalling offers to
; remove them, with No as the default. /DELETEUSERDATA=1 says yes for a silent uninstall.

#ifndef AppVersion
  #error Build with packaging/build.py --installer
#endif

[Setup]
AppId={{B6D1F0E2-5B7A-4C3E-9A41-7E2C8D5F1A63}
AppName=TTSPython
AppVersion={#AppVersion}
AppVerName=TTSPython {#AppVersion}
AppPublisher=Pure Tech
AppPublisherURL=https://github.com/JoshLongmire/TTSPython
AppSupportURL=https://github.com/JoshLongmire/TTSPython/issues
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\TTSPython
DefaultGroupName=TTSPython
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#AppDir}\LICENSE.txt
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\TTSPython.exe
UninstallDisplayName=TTSPython
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
OutputDir={#OutDir}
OutputBaseFilename=TTSPython-{#AppVersion}-windows-x64-setup
#ifdef TryOut
; For trying the installer on a development PC: it adds nothing to the Apps list or the Start menu.
CreateUninstallRegKey=no
#endif

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[InstallDelete]
; An older version's libraries must not stay next to the new ones.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

#ifndef TryOut
[Icons]
Name: "{autoprograms}\TTSPython"; Filename: "{app}\TTSPython.exe"
Name: "{autodesktop}\TTSPython"; Filename: "{app}\TTSPython.exe"; Tasks: desktopicon
#endif

[Run]
Filename: "{app}\TTSPython.exe"; Description: "Start TTSPython"; Flags: nowait postinstall skipifsilent

[Code]
function FileInUse(const Path: String): Boolean;
var
  Stream: TFileStream;
begin
  Result := False;
  try
    Stream := TFileStream.Create(Path, fmOpenReadWrite or fmShareExclusive);
    Stream.Free;
  except
    Result := True;
  end;
end;

// Asks a running copy to quit, so it saves its settings, and waits until its files are free:
// --quit only passes on the request. A copy asking about unsaved text gets time for an answer.
procedure QuitRunningApp;
var
  AppExe: String;
  ExitCode, Tries: Integer;
begin
  AppExe := ExpandConstant('{app}\TTSPython.exe');
  if not FileExists(AppExe) then
    Exit;
  if not Exec(AppExe, '--quit', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    Exit;
  Tries := 0;
  while FileInUse(AppExe) and (Tries < 120) do
  begin
    Sleep(500);
    Tries := Tries + 1;
  end;
end;

// Installing over a running copy would pull its libraries out from under it.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  QuitRunningApp;
  if FileInUse(ExpandConstant('{app}\TTSPython.exe')) and FileExists(ExpandConstant('{app}\TTSPython.exe')) then
    Result := 'TTSPython is still running. Close it, answer any question it is asking, and run setup again.'
  else
    Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  QuitRunningApp;
  Result := not (FileExists(ExpandConstant('{app}\TTSPython.exe')) and FileInUse(ExpandConstant('{app}\TTSPython.exe')));
  if not Result then
    SuppressibleMsgBox('TTSPython is still running. Close it, answer any question it is asking, and uninstall again.',
                       mbError, MB_OK, IDOK);
end;

procedure DeleteUserData;
var
  Root: String;
begin
#ifdef TryOut
  // A try-out on a development PC must never reach the real folders.
  Root := GetEnv('TTSPYTHON_TRYOUT_DATA');
  if Root = '' then
    Exit;
  DelTree(Root + '\Roaming\TTSPython', True, True, True);
  DelTree(Root + '\Local\TTSPython', True, True, True);
#else
  DelTree(ExpandConstant('{userappdata}\TTSPython'), True, True, True);
  DelTree(ExpandConstant('{localappdata}\TTSPython'), True, True, True);
#endif
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  if UninstallSilent then
  begin
    if ExpandConstant('{param:DELETEUSERDATA|0}') = '1' then
      DeleteUserData;
  end
  else if MsgBox('Also delete your settings, unsaved text, voices, voice recordings and downloaded voices?' + #13#10 + #13#10 +
                 'Choose No to keep them for next time. Speech recognition models are kept either way: ' +
                 'delete those first in Settings > Listen.',
                 mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    DeleteUserData;
end;
