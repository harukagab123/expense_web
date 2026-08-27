#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{A29B1C73-C69F-4F19-887D-73CFBD7D3AE1}
AppName=Personal Finance Manager
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\PersonalFinanceManager
DefaultGroupName=Personal Finance Manager
OutputDir=..\outputs\release
OutputBaseFilename=PersonalFinanceManager-{#MyAppVersion}-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\PersonalFinanceManager.exe

[Files]
Source: "..\outputs\release\PersonalFinanceManager.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\USER_GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Personal Finance Manager"; Filename: "{app}\PersonalFinanceManager.exe"
Name: "{autodesktop}\Personal Finance Manager"; Filename: "{app}\PersonalFinanceManager.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\PersonalFinanceManager.exe"; Description: "Launch Personal Finance Manager"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM PersonalFinanceManager.exe"; Flags: runhidden waituntilterminated; RunOnceId: "ClosePersonalFinanceManager"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  CloseResultCode: Integer;
  ExistingExe: String;
begin
  Result := '';
  ExistingExe := ExpandConstant('{app}\PersonalFinanceManager.exe');
  if FileExists(ExistingExe) then
  begin
    if not Exec(ExistingExe, '--prepare-update {#MyAppVersion}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      Result := 'Update stopped because the required safety backup could not be created. Your installed application and data were not changed.';
    if Result = '' then
    begin
      { The windowless launcher has no top-level window for Restart Manager to
        close. Stop only this product's explicitly named processes, and only
        after the installed version created and validated its safety backup. }
      Exec(
        ExpandConstant('{sys}\taskkill.exe'),
        '/F /IM PersonalFinanceManager.exe',
        '',
        SW_HIDE,
        ewWaitUntilTerminated,
        CloseResultCode
      );
      Sleep(500);
    end;
  end;
end;
