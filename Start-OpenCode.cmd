@echo off
setlocal
set "PATH=%APPDATA%\npm;%PATH%"
set "TERM=xterm-256color"
for /f "usebackq delims=" %%I in (`powershell.exe -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias Ethernet | Where-Object {$_.IPAddress -notlike '169.254*'} | Select-Object -First 1 -ExpandProperty IPAddress)"`) do set "LMSTUDIO_BASE_URL=http://%%I:1234/v1"
if not defined LMSTUDIO_BASE_URL (
  echo Could not find the Ethernet address used to reach LM Studio.
  pause
  exit /b 1
)
cd /d L:\LocalCoder
rem Report the configured model's actual LM Studio state without loading or unloading it.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File L:\LocalCoder\.opencode\evals\check_lmstudio_model.ps1 -BaseUrl "%LMSTUDIO_BASE_URL%"
if errorlevel 1 (
  echo Could not verify the configured model through LM Studio.
  pause
  exit /b 1
)
rem Refresh LM Studio discovery before selecting the configured model.
call opencode --standalone models >nul
if errorlevel 1 (
  echo OpenCode could not discover LM Studio models at %LMSTUDIO_BASE_URL%.
  pause
  exit /b 1
)
opencode --standalone %*
