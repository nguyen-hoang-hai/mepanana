@echo off
setlocal
chcp 65001 >nul
title MEPANANA Extension - 1-Click Installer
color 0A
cls

if exist "%~dp0tools\installer\install.ps1" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\installer\install.ps1"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://raw.githubusercontent.com/nguyen-hoang-hai/mepanana/main/tools/installer/install.ps1', \"$env:TEMP\mepanana_install.ps1\"); & \"$env:TEMP\mepanana_install.ps1\"; Remove-Item \"$env:TEMP\mepanana_install.ps1\" -Force -ErrorAction SilentlyContinue"
)

echo.
pause
