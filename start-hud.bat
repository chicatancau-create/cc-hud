@echo off
rem cc-hud launcher: React + pywebview (Edge WebView2). Legacy tkinter build removed.
setlocal
cd /d "%~dp0"
if not exist "web\dist\index.html" (
  echo [cc-hud] web\dist\index.html missing - run: cd web ^&^& npm install ^&^& npm run build
  pause
  exit /b 1
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo [cc-hud] .venv\Scripts\pythonw.exe missing
  pause
  exit /b 1
)
rem 不再用第二个 pythonw 预检 import webview（那会把 pywebview 导入两遍、多一个进程）。
rem 依赖缺失由 cc-hud.pyw 自己用 MessageBox 报错，pythonw 不会静默退出。
start "" ".venv\Scripts\pythonw.exe" "%~dp0cc-hud.pyw"
