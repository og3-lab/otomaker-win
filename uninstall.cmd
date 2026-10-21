@echo off
setlocal
rem Remove the otomaker registration from Claude Desktop / Claude Code / OpenAI Codex. Files are not deleted.
if not exist "%~dp0installer\uninstall.ps1" (
  echo Extract the whole zip first, then run uninstall.cmd in the extracted folder.
  pause
  exit /b 1
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\uninstall.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if not defined OTOMAKER_NO_PAUSE pause
exit /b %RC%
