# build/build.ps1
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = (Get-Location).Path
$src = Join-Path $root "src\xtts_local.py"
$distDir = Join-Path $root "dist\xtts_local"
$icon = Join-Path $root "assets\icon.ico"

if (-not (Test-Path $src)) {
    Write-Error "Source file not found: $src"
    exit 1
}

# Clean previous builds
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue -Path './build/pyinstaller','./build/__pycache__','./dist','./build','./xtts_local_installer.exe'

# Prepare PyInstaller add-data only if ffmpeg exists
$addData = $null
if (Test-Path (Join-Path $root 'ffmpeg')) {
    $addData = "ffmpeg;ffmpeg"
}

# Build args
$pyinstallerArgs = @(
    "--noconfirm"
    "--onedir"
)
if ($addData) {
    $pyinstallerArgs += @("--add-data", $addData)
}
$pyinstallerArgs += @("--name", "xtts_local", $src)

if (Test-Path $icon) {
    $pyinstallerArgs += @("--icon", $icon)
}

Write-Output "Running PyInstaller with args: $($pyinstallerArgs -join ' ')"
python -m PyInstaller @pyinstallerArgs

if (-not (Test-Path $distDir)) {
    Write-Error "PyInstaller did not produce expected dist folder: $distDir"
    exit 1
}

# Copy README and license if present
if (Test-Path .\README.md) { Copy-Item .\README.md $distDir -Force }

# Create installer using NSIS script (makensis will be invoked by workflow)
# Also create a zip fallback
$zipPath = Join-Path $root "xtts_local_release.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path (Join-Path $distDir '*') -DestinationPath $zipPath -Force

Write-Output "Build complete. Dist folder: $distDir"
