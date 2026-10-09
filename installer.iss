; 小狗桌宠 —— Inno Setup 安装包脚本
; 用法：用 Inno Setup 打开本文件，或命令行 ISCC.exe installer.iss
;
; 前置条件：先跑 PyInstaller 生成 dist\DesktopPet\
;   python -m PyInstaller --noconfirm --clean --name DesktopPet --windowed ^
;     --icon assets/icon.ico --add-data "assets/pet;assets/pet" ^
;     --add-data "assets/game;assets/game" --add-data "assets/fonts;assets/fonts" ^
;     --add-data "assets/sfx;assets/sfx" --add-data "assets/icon.ico;assets" ^
;     --add-data "assets/icon.png;assets" --add-data "assets/cards;assets/cards" ^
;     --add-data "custom_pet/*.png;assets/pet" ^
;     --add-data "custom_pet/facing.json;assets/pet" --exclude-module tkinter main.py
;
; 注：`assets/cards`（104 张卡池 + cards.json）是 v2.3.0 加的，v2.4.0 补进这一行 ——
; 漏了它打出来的安装包没有卡册，而开发态直接读项目根，看不出问题。

#define AppName "小狗桌宠"
#define AppVer "2.4.0"
#define AppExe "DesktopPet.exe"
#define AppPublisher "王蓬"

[Setup]
AppId={{9A3F2C71-4E8B-4D62-B5A1-7C6E0D9F2B43}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableDirPage=auto
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=小狗桌宠_v{#AppVer}_安装包
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce
Name: "autostart"; Description: "开机自动启动（推荐，开机会自动出现）"

[Files]
Source: "dist\DesktopPet\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "custom_pet\*.png"; DestDir: "{userappdata}\DesktopPet\custom_pet"; Flags: ignoreversion uninsneveruninstall
Source: "custom_pet\facing.json"; DestDir: "{userappdata}\DesktopPet\custom_pet"; Flags: ignoreversion uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "立即启动桌宠"; Flags: nowait postinstall skipifsilent

[Messages]
SetupAppTitle=安装程序
SetupWindowTitle=安装 - %1
UninstallAppTitle=卸载程序
UninstallAppFullTitle=卸载 - %1
ButtonNext=下一步(&N) >
ButtonBack=< 上一步(&B)
ButtonInstall=安装(&I)
ButtonFinish=完成(&F)
ButtonCancel=取消
ButtonBrowse=浏览(&R)...
ButtonYes=是(&Y)
ButtonNo=否(&N)
WelcomeLabel1=欢迎使用 %1 安装向导
WelcomeLabel2=现在将把 [name/ver] 安装到您的电脑。%n%n建议先关闭其它程序，然后点击"下一步"继续。
WizardSelectDir=选择目标位置
SelectDirDesc=您想将 [name] 安装到哪里？
SelectDirLabel3=安装程序将把 [name] 安装到下面的文件夹。
SelectDirBrowseLabel=点击"下一步"继续；想换文件夹请点击"浏览"。
WizardSelectTasks=选择附加任务
SelectTasksDesc=您想执行哪些附加任务？
SelectTasksLabel2=安装 [name] 时执行以下附加任务，不需要的可以取消勾选：
WizardReady=准备安装
ReadyLabel1=安装程序已准备好，即将把 [name] 安装到您的电脑。
ReadyLabel2a=点击"安装"开始安装；想检查或修改设置请点击"上一步"。
WizardInstalling=正在安装
InstallingLabel=正在安装 [name]，请稍候……
FinishedHeadingLabel=[name] 安装完成
FinishedLabel=安装程序已完成 [name] 的安装。%n%n点击"完成"退出。
FinishedLabelNoIcons=安装程序已完成 [name] 的安装。%n%n点击"完成"退出。
ClickFinish=点击"完成"按钮退出。
RunEntryExec=运行 %1
ConfirmUninstall=确定要完全卸载 %1 及其所有组件吗？
UninstalledAll=%1 已成功卸载。
UninstalledMost=%1 卸载完成。%n%n有少数文件需要手动删除。
UninstallStatusLabel=正在卸载 %1，请稍候……
