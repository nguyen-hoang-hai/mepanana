@echo off
chcp 65001 >nul
title MEPANANA Extension - 1-Click Installer
color 0A
cls
echo ======================================================================
echo          🍌 MEPANANA REVIT EXTENSION - BỘ CÀI ĐẶT 1-CLICK
echo ======================================================================
echo  * Chế độ: User-Level (Không cần quyền Administrator)
echo  * Nguồn tải: GitHub (nguyen-hoang-hai/mepanana)
echo ======================================================================
echo.
echo  [1/3] Đang kết nối GitHub và tải bản cập nhật mới nhất...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop'; " ^
  "$ProgressPreference = 'SilentlyContinue'; " ^
  "[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12; " ^
  "$zipUrl = 'https://github.com/nguyen-hoang-hai/mepanana/archive/refs/heads/main.zip'; " ^
  "$tempZip = [System.IO.Path]::Combine($env:TEMP, 'mepanana_latest.zip'); " ^
  "$tempExtract = [System.IO.Path]::Combine($env:TEMP, 'mepanana_extracted'); " ^
  "$extDir = [System.IO.Path]::Combine($env:APPDATA, 'pyRevit', 'Extensions', 'mepanana.extension'); " ^
  "(New-Object System.Net.WebClient).DownloadFile($zipUrl, $tempZip); " ^
  "Write-Host ' [2/3] Đang cài đặt vào thư mục %APPDATA%\pyRevit\Extensions...'; " ^
  "if (Test-Path $tempExtract) { Remove-Item -Path $tempExtract -Recurse -Force }; " ^
  "Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force; " ^
  "$innerDir = [System.IO.Path]::Combine($tempExtract, 'mepanana-main'); " ^
  "if (-not (Test-Path $extDir)) { New-Item -ItemType Directory -Path $extDir -Force | Out-Null }; " ^
  "Copy-Item -Path \"$innerDir\*\" -Destination $extDir -Recurse -Force; " ^
  "Remove-Item -Path $tempZip -Force -ErrorAction SilentlyContinue; " ^
  "Remove-Item -Path $tempExtract -Recurse -Force -ErrorAction SilentlyContinue; " ^
  "Write-Host ' [3/3] Đăng ký thành công tiện ích MEPANANA với pyRevit!'"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ======================================================================
    echo  🎉 CHÚC MỪNG: CÀI ĐẶT / CẬP NHẬT MEPANANA THÀNH CÔNG!
    echo  👉 Hãy mở hoặc khởi động lại Autodesk Revit để sử dụng tiện ích.
    echo ======================================================================
) else (
    echo.
    echo ======================================================================
    echo  ❌ CÓ LỖI XẢY RA: Vui lòng kiểm tra kết nối mạng Internet và thử lại.
    echo ======================================================================
)
echo.
pause
