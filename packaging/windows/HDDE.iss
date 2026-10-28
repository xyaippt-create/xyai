#ifndef SourceDir
  #error SourceDir must be provided by build_release.ps1
#endif
#ifndef OutputDir
  #error OutputDir must be provided by build_release.ps1
#endif
#ifndef ProductVersion
  #error ProductVersion must be provided by build_release.ps1
#endif
#ifndef InstallerVersion
  #error InstallerVersion must be provided by build_release.ps1
#endif
#ifndef DisplayVersion
  #error DisplayVersion must be provided by build_release.ps1
#endif
#ifndef PackageBaseName
  #error PackageBaseName must be provided by build_release.ps1
#endif
#ifndef WebView2Bootstrapper
  #error WebView2Bootstrapper must be provided by build_release.ps1
#endif

[Setup]
AppId={{54CA1D9A-F271-4C8B-B8C0-613D2411F7AB}
AppName=影界 HDDE
AppVersion={#ProductVersion}
AppVerName=影界 HDDE {#DisplayVersion}
VersionInfoVersion={#InstallerVersion}
VersionInfoProductVersion={#InstallerVersion}
VersionInfoDescription=影界 HDDE 内测版安装程序
DefaultDirName={localappdata}\Programs\影界 HDDE
DefaultGroupName=影界 HDDE
UninstallDisplayIcon={app}\影界 HDDE.exe
OutputDir={#OutputDir}
OutputBaseFilename={#PackageBaseName}
SetupIconFile={#SourceDir}\_internal\dist\branding\hdde\hdde.ico
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
WizardStyle=modern

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebView2Bootstrapper}"; Flags: dontcopy

[Icons]
Name: "{group}\影界 HDDE"; Filename: "{app}\影界 HDDE.exe"; WorkingDir: "{app}"
Name: "{group}\退出影界 HDDE"; Filename: "{app}\影界 HDDE.exe"; Parameters: "--shutdown"; WorkingDir: "{app}"
Name: "{autodesktop}\影界 HDDE"; Filename: "{app}\影界 HDDE.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\影界 HDDE.exe"; Description: "启动影界 HDDE"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2ClientKey = 'Software\Microsoft\EdgeUpdate\Clients\{F1E7E9C9-AF2C-4AA4-8A41-1B81F49BFCF7}';
  WebView2BootstrapperName = 'MicrosoftEdgeWebView2Setup.exe';

function HasUsableWebView2Version(RootKey: Integer): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, WebView2ClientKey, 'pv', Version) and
    (Version <> '') and (Version <> '0.0.0.0');
end;

function HasWebView2RuntimeFiles(RootDirectory: String): Boolean;
var
  FindRec: TFindRec;
  RuntimeExecutable: String;
  Version: String;
begin
  Result := False;
  if not DirExists(RootDirectory) then
    exit;
  if FindFirst(AddBackslash(RootDirectory) + '*', FindRec) then
  begin
    try
      repeat
        if ((FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
          (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          RuntimeExecutable := AddBackslash(RootDirectory) + FindRec.Name +
            '\msedgewebview2.exe';
          if FileExists(RuntimeExecutable) and
            GetVersionNumbersString(RuntimeExecutable, Version) and (Version <> '') then
          begin
            Result := True;
            exit;
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function IsWebView2RuntimeInstalled(): Boolean;
begin
  Result := HasUsableWebView2Version(HKCU) or
    HasUsableWebView2Version(HKLM32) or
    HasUsableWebView2Version(HKLM64) or
    HasWebView2RuntimeFiles(ExpandConstant('{pf32}\Microsoft\EdgeWebView\Application')) or
    HasWebView2RuntimeFiles(ExpandConstant('{localappdata}\Microsoft\EdgeWebView\Application'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  if IsWebView2RuntimeInstalled() then
    exit;

  ExtractTemporaryFile(WebView2BootstrapperName);
  if not Exec(ExpandConstant('{tmp}\' + WebView2BootstrapperName),
    '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Result := '无法启动 Microsoft Edge WebView2 Runtime 安装程序。影界 HDDE 尚未安装。';
    exit;
  end;
  if (ResultCode <> 0) or not IsWebView2RuntimeInstalled() then
    Result := 'Microsoft Edge WebView2 Runtime 安装未完成。请联网后重试影界 HDDE 安装。';
end;
