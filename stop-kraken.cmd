@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-kraken.ps1" %*
exit /b %ERRORLEVEL%
