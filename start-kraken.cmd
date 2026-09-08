@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-kraken.ps1" %*
exit /b %ERRORLEVEL%
