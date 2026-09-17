# Prosperya Preview — reproducible Windows build pipeline.
#
#   .\build_preview.ps1            # frontend build + PyInstaller bundle
#   .\build_preview.ps1 -Installer # also compiles the Inno Setup installer
#                                  (requires Inno Setup 6 on PATH or default location)
#
# Output:
#   backend\dist\Prosperya\            onedir application bundle
#   dist\Prosperya Preview Setup.exe   installer (with -Installer)
param([switch]$Installer, [switch]$Console)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $repo ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $repo ".venv\Scripts\pyinstaller.exe"

Write-Host "==> 1/3 Frontend production build" -ForegroundColor Cyan
Push-Location (Join-Path $repo "frontend")
npm run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
Pop-Location

Write-Host "==> 2/3 PyInstaller bundle" -ForegroundColor Cyan
if ($Console) { $env:PROSPERYA_CONSOLE = "1" } else { Remove-Item Env:\PROSPERYA_CONSOLE -ErrorAction SilentlyContinue }
Push-Location (Join-Path $repo "backend")
& $pyinstaller prosperya.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Pop-Location

if ($Installer) {
    Write-Host "==> 3/3 Inno Setup installer" -ForegroundColor Cyan
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $iscc) {
        $candidates = @(
            "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            "C:\Program Files\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
        )
        $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    } else { $iscc = $iscc.Source }
    if (-not $iscc) { throw "Inno Setup 6 not found. Install it from https://jrsoftware.org/isinfo.php" }
    & $iscc (Join-Path $repo "installer\prosperya_preview.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed" }
}

Write-Host ""
Write-Host "Build complete." -ForegroundColor Green
Write-Host "  Bundle:    backend\dist\Prosperya\Prosperya.exe"
if ($Installer) { Write-Host "  Installer: dist\Prosperya Preview Setup.exe" }
