@echo off
rem 启动 CC Switch HUD（无控制台窗口）
rem
rem 解释器必须钉死成 D:\PyCharm\Python\pythonw.exe（GIL 版 3.14），不能写裸 `pythonw`：
rem   1) free-threaded 的 python3.14t.exe —— 与 GIL 版共用 site-packages，但 Pillow 的
rem      C 扩展 _imaging.pyd 是按 GIL ABI 编译的，导入必失败：
rem      "cannot import name '_imaging' from 'PIL._typing'"（2026-11-02 实测）。
rem      而 .pyw 关联到 C:\Windows\pyw.exe，它默认会挑 3.14t —— 直接双击 .pyw 也会踩这个坑。
rem   2) 托管环境 PATH 里的 pythonw 指向 ...\.workbuddy-ai\...\3.13.12\pythonw.exe，
rem      那个构建**没有 tkinter**，同样起不来。
rem 下面先自检再 start：起不来时给一句人话，而不是静默消失。
setlocal
set "PYW=D:\PyCharm\Python\pythonw.exe"
if not exist "%PYW%" (
    echo [x] 找不到解释器：%PYW%
    pause
    exit /b 1
)
"%PYW%" -c "import tkinter, PIL.Image" 2>nul
if errorlevel 1 (
    echo [x] %PYW% 缺少 tkinter 或 Pillow，无法启动 HUD。
    pause
    exit /b 1
)
start "" "%PYW%" "%~dp0cc-hud.pyw"
