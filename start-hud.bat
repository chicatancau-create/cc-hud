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
".venv\Scripts\pythonw.exe" -c "import webview" >/dev/null 2>&1
if errorlevel 1 (
  echo [cc-hud] pywebview missing in .venv
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0cc-hud.pyw"
