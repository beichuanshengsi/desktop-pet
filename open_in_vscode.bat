@echo off
chcp 65001 >nul
rem 用 VS Code 打开本工作区。
rem 如果提示找不到 code，说明没把 VS Code 加进 PATH：
rem   VS Code 里按 Ctrl+Shift+P -> 输入 "Shell Command: Install 'code' command in PATH"
rem 或者直接双击 desktop-pet.code-workspace 也一样。

cd /d "%~dp0"
start "" code "desktop-pet.code-workspace"
if errorlevel 1 (
    echo [提示] 没找到 code 命令，改为直接打开工作区文件...
    start "" "desktop-pet.code-workspace"
)
exit /b 0
