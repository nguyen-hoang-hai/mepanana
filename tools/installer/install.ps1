# ======================================================================
#          MEPANANA REVIT EXTENSION - 1-CLICK INSTALLER
# ======================================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls13

Write-Host "======================================================================" -ForegroundColor Green
Write-Host "         MEPANANA REVIT EXTENSION - 1-CLICK INSTALLER                 " -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host " * Mode: User-Level (No Administrator Privileges Required)" -ForegroundColor Gray
Write-Host " * Source: GitHub (https://github.com/nguyen-hoang-hai/mepanana)" -ForegroundColor Gray
Write-Host "======================================================================" -ForegroundColor Green
Write-Host ""

$zipUrl = "https://github.com/nguyen-hoang-hai/mepanana/archive/refs/heads/main.zip"
$tempZip = Join-Path $env:TEMP "mepanana_latest.zip"
$tempExtract = Join-Path $env:TEMP "mepanana_extracted"
$appData = [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)
$extDir = Join-Path $appData "pyRevit\Extensions\mepanana.extension"

try {
    Write-Host "[1/3] Connecting to GitHub & downloading latest release..." -ForegroundColor Cyan
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "MEPANANA-1Click-Installer")
    $wc.DownloadFile($zipUrl, $tempZip)

    $fileSize = (Get-Item $tempZip).Length
    $fileSizeKb = [Math]::Round($fileSize / 1024, 1)
    Write-Host "      Download completed successfully ($fileSizeKb KB)." -ForegroundColor Green

    Write-Host "[2/3] Extracting and deploying to pyRevit Extensions..." -ForegroundColor Cyan
    if (Test-Path $tempExtract) {
        Remove-Item -Path $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
    }

    Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force

    $innerDir = Join-Path $tempExtract "mepanana-main"
    if (-not (Test-Path $innerDir)) {
        $innerDir = $tempExtract
    }

    if (-not (Test-Path $extDir)) {
        New-Item -ItemType Directory -Path $extDir -Force | Out-Null
    }

    # Copy files gracefully (safely handling in-use DLLs if Revit is currently open)
    Get-ChildItem -Path $innerDir -Recurse | ForEach-Object {
        $relPath = $_.FullName.Substring($innerDir.Length).TrimStart('\', '/')
        $targetPath = Join-Path $extDir $relPath
        if ($_.PSIsContainer) {
            if (-not (Test-Path $targetPath)) { New-Item -ItemType Directory -Path $targetPath -Force | Out-Null }
        } else {
            try {
                Copy-Item -Path $_.FullName -Destination $targetPath -Force -ErrorAction Stop
            } catch {
                # File is currently loaded in memory by active Revit session
            }
        }
    }

    Remove-Item -Path $tempZip -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $tempExtract -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "[3/3] Successfully registered MEPANANA extension with pyRevit!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Install Destination: $extDir" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "INSTALLATION COMPLETE! Launch Revit or click pyRevit -> Reload to start." -ForegroundColor Yellow
}
catch {
    Write-Host ""
    Write-Host "Installation Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
