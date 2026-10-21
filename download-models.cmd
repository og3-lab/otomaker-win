@echo off
setlocal
rem Download (more) OtoMaker model files. Run install.cmd first.
if not exist "%~dp0installer\download-models.ps1" (
  echo Extract the whole zip first, then run download-models.cmd in the extracted folder.
  pause
  exit /b 1
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\download-models.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if not defined OTOMAKER_NO_PAUSE pause
exit /b %RC%
