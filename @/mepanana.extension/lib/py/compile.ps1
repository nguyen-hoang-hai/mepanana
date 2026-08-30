# compile.ps1 — Compile CadExtractor.cs -> CadExtractor.dll (MepananaCSharp namespace)
# Run once after any C# change. Requires Revit to be installed.

$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$csFile      = Join-Path $scriptDir "CadExtractor.cs"
$outDll      = Join-Path $scriptDir "CadExtractor.dll"

# ── Find csc.exe ──────────────────────────────────────────────────────────────
$cscCmd = Get-Command csc -ErrorAction SilentlyContinue
$csc = if ($cscCmd) { $cscCmd.Source } else { $null }
if (-not $csc) {
    $csc = Get-ChildItem "C:\Windows\Microsoft.NET\Framework64" -Filter "csc.exe" -Recurse |
           Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $csc) { Write-Error "csc.exe not found."; exit 1 }

# ── Revit API references ──────────────────────────────────────────────────────
$revitFolder = (Get-ItemProperty "HKLM:\SOFTWARE\Autodesk\Revit\*" -ErrorAction SilentlyContinue |
    Sort-Object InstallLocation -Descending | Select-Object -First 1).InstallLocation

if (-not $revitFolder) {
    # Fallback to common path
    $revitFolder = "C:\Program Files\Autodesk\Revit 2025"
}

$refs = @(
    (Join-Path $revitFolder "RevitAPI.dll"),
    (Join-Path $revitFolder "RevitAPIUI.dll")
)
foreach ($r in $refs) {
    if (-not (Test-Path $r)) { Write-Warning "Reference not found: $r" }
}
$refArgs = ($refs | ForEach-Object { "/reference:`"$_`"" }) -join " "

# ── Compile ───────────────────────────────────────────────────────────────────
$cmd = "& `"$csc`" /target:library /optimize+ /out:`"$outDll`" $refArgs `"$csFile`""
Write-Host "Compiling..." -ForegroundColor Cyan
Invoke-Expression $cmd

if ($LASTEXITCODE -eq 0) {
    Write-Host "Done: $outDll" -ForegroundColor Green
} else {
    Write-Error "Compilation failed."
}
