@echo off
rem Shema - installs or updates the PC side. Double click. Safe to run again.
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
