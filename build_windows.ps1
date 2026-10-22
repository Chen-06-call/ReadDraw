param(
    [switch]$OneDir,
    [string]$Version = "v0.0.4"
)

$ErrorActionPreference = "Stop"
$normalizedVersion = $Version.Trim().TrimStart("v")
if ($normalizedVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must look like v0.0.0 or 0.0.0."
}
$env:READDRAW_VERSION = $normalizedVersion
$scripts = python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
$flet = Join-Path $scripts.Trim() "flet.exe"
if (-not (Test-Path -LiteralPath $flet)) {
    $pythonFolder = python -c "import sys; print(f'Python{sys.version_info.major}{sys.version_info.minor}')"
    $flet = Join-Path $env:APPDATA "Python\$($pythonFolder.Trim())\Scripts\flet.exe"
}
if (-not (Test-Path -LiteralPath $flet)) {
    throw "Flet CLI was not found. Install dependencies with: python -m pip install -r requirements.txt"
}
$iconPath = Join-Path (Get-Location) "assets\ReadDraw.ico"
if (-not (Test-Path -LiteralPath $iconPath)) {
    throw "Application icon not found: $iconPath"
}
$arguments = @(
    "pack", "main.py", "--name", "ReadDraw", "--icon", $iconPath, "--distpath", "dist", "--yes"
)
if ($OneDir) {
    $arguments += "--onedir"
}
# Rendering and text search use MuPDF itself. The optional AI layout package
# loads ONNX native libraries at import time and can crash a frozen Windows app.
$arguments += @("--", "--exclude-module=pymupdf.layout", "--exclude-module=onnxruntime")
& $flet @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Flet package build failed; release files were not updated."
}
$releaseDirectory = Join-Path (Get-Location) "release"
New-Item -ItemType Directory -Force -Path $releaseDirectory | Out-Null
$sourceExe = if ($OneDir) {
    Join-Path (Get-Location) "dist\ReadDraw\ReadDraw.exe"
} else {
    Join-Path (Get-Location) "dist\ReadDraw.exe"
}
if (-not (Test-Path -LiteralPath $sourceExe)) {
    throw "Build output not found: $sourceExe"
}
$releaseExe = Join-Path $releaseDirectory "ReadDraw-v$normalizedVersion-windows-x64.exe"
Copy-Item -LiteralPath $sourceExe -Destination $releaseExe -Force
$hash = (Get-FileHash -LiteralPath $releaseExe -Algorithm SHA256).Hash.ToLowerInvariant()
$shaPath = "$releaseExe.sha256"
"$hash  $(Split-Path $releaseExe -Leaf)" | Set-Content -LiteralPath $shaPath -Encoding ascii
$manifest = [ordered]@{
    version = $normalizedVersion
    tag = "v$normalizedVersion"
    product = "ReadDraw"
    platform = "windows-x64"
    asset = (Split-Path $releaseExe -Leaf)
    sha256 = $hash
    release_url = "https://github.com/Chen-06-call/ReadDraw/releases/tag/v$normalizedVersion"
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releaseDirectory "update.json") -Encoding utf8
$makensis = Get-Command makensis.exe -ErrorAction SilentlyContinue
if ($makensis) {
    $installerScript = Join-Path (Get-Location) "installer\ReadDraw.nsi"
    & $makensis.Source "/DAPP_VERSION=$normalizedVersion" "/DEXE_PATH=$sourceExe" $installerScript
    if ($LASTEXITCODE -ne 0) {
        throw "NSIS installer build failed."
    }
}
Write-Host "ReadDraw package created: $sourceExe"
Write-Host "Release assets created under $releaseDirectory"
