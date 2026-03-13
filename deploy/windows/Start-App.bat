@echo off
setlocal

set "ROOT_DIR=%~dp0\..\.."
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"

start "Multi-LLM Doc Agent Watchdog" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT_DIR%\deploy\windows\Start-Watchdog.ps1" -RepoPath "%ROOT_DIR%"

echo Watchdog started in background.
echo Logs: %ROOT_DIR%\artifacts\runtime\logs
endlocal
