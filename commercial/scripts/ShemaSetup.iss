; Shema (שמע) -- one-file Windows installer.  Built by build_setup.ps1 (the release dashboard and CI call it):
;   build_setup.ps1 1.0.15   ->  commercial\dist\ShemaSetup.exe   (ISCC /DAppVersion=.. /DSrc=<staged committed files>)
; It unpacks the PC side (server\, install\, requirements.txt) to %LOCALAPPDATA%\Shema\setup and runs install\install.ps1,
; the same installer Install.bat runs (Python, models, firewall rule, background task, "שמע" shortcuts on the desktop and
; in the Start menu). No admin rights: install.ps1 asks Windows once, only for the firewall rule.
; Testing: ShemaSetup.exe /SILENT /SHEMAARGS="-Test -Quiet -SkipModels -SkipOllama -Port 8771 -ShemaHome C:\x"

#ifndef Src
  #define Src "..\.."
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B0E3C1D-5A7F-4C2E-9B1A-3F8D2E7C4A10}
AppName=שמע
AppVerName=שמע {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=Shema
AppPublisherURL=https://shema.agmonp.com/
; file properties of ShemaSetup.exe (SignPath checks product name + version before it signs)
VersionInfoProductName=Shema
VersionInfoDescription=Shema Setup
VersionInfoCompany=Shema
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
AppSupportURL=https://github.com/agmonp/shema/issues
SourceDir={#Src}
DefaultDirName={localappdata}\Shema\setup
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=ShemaSetup
SetupIconFile=server\ui\shema.ico
UninstallDisplayIcon={app}\server\ui\shema.ico
UninstallDisplayName=שמע
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=no

[Languages]
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"

[Messages]
hebrew.WelcomeLabel2=ההתקנה תכין את שמע במחשב הזה: תוכנת השרת, Python והמודלים לתמלול בעברית (כמה GB בפעם הראשונה, ולכן זה לוקח זמן).%n%nהכל נשאר במחשב שלך, בלי ענן.
hebrew.FinishedLabel=שמע מותקן ופועל ברקע. הסמל "שמע" בשולחן העבודה ובתפריט התחל פותח את המסך שלו.

[Files]
Source: "server\*"; DestDir: "{app}\server"; Excludes: "__pycache__,*.pyc,.pytest_cache"; Flags: recursesubdirs ignoreversion
Source: "install\*"; DestDir: "{app}\install"; Flags: recursesubdirs ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "{code:HomeUrl}"; Description: "פתח את שמע"; Flags: postinstall shellexec nowait skipifsilent; Check: InstallOk

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install\uninstall.ps1"" -Confirmed"; Flags: waituntilterminated; RunOnceId: "ShemaUninstall"

[Code]
var
  Ok: Boolean;

function InstallOk: Boolean;
begin
  Result := Ok;
end;

{ install.ps1 writes the port it chose (8770, or the next free one) to %LOCALAPPDATA%\Shema\port.txt }
function HomeUrl(Param: String): String;
var
  Port: AnsiString;
begin
  if not LoadStringFromFile(ExpandConstant('{localappdata}\Shema\port.txt'), Port) then
    Port := '8770';
  Port := Trim(Port);
  if Port = '' then
    Port := '8770';
  Result := 'http://localhost:' + Port + '/home#pair';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Params: String;
begin
  if CurStep <> ssPostInstall then exit;
  WizardForm.StatusLabel.Caption := 'מתקין את Python, ffmpeg והמודלים. החלון השחור מראה את ההתקדמות; אל תסגור אותו.';
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\install\install.ps1') + '" -NoLaunch ' +
            ExpandConstant('{param:SHEMAARGS|}');
  if not Exec('powershell.exe', Params, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, Code) then
    Code := -1;
  Ok := (Code = 0);
  if not Ok then
    SuppressibleMsgBox('ההתקנה לא הושלמה (קוד ' + IntToStr(Code) + ').' + #13#10 +
      'הפרטים בקובץ ' + ExpandConstant('{localappdata}\Shema\install.log') + #13#10 +
      'אפשר להריץ שוב את ShemaSetup.exe: הוא ממשיך מאיפה שנעצר.', mbError, MB_OK, IDOK);
end;
