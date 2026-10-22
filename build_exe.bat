@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Initialize-Build.ps1"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Install-InnoSetup.ps1"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Build-Windows.ps1" -Channel Development
exit /b %ERRORLEVEL%
