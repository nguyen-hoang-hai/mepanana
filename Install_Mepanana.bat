@echo off
chcp 65001 >nul
title MEPANANA Extension - 1-Click Installer
echo ======================================================================
echo          MEPANANA REVIT EXTENSION - 1-CLICK INSTALLER
echo ======================================================================
echo  * Mode: User-Level (No Admin Rights Required)
echo  * Source: GitHub (https://github.com/nguyen-hoang-hai/mepanana)
echo ======================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; & '%~dp0tools\installer\install.ps1' }"

echo.
echo Press any key to exit...
pause >nul

