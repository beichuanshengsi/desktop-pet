@echo off
rem 双击运行桌宠。
rem 这里刻意不写死用户名路径：%USERPROFILE% 由系统在运行时展开，
rem 所以本文件本身保持纯 ASCII，不受中文用户名编码问题影响。
setlocal

set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"

start "" "%PYW%" "%~dp0main.py"
endlocal
