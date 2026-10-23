param(
    [switch]$OneDir,
    [string]$Version = "v0.1.8",
    [switch]$RequireInstaller
)

$ErrorActionPreference = "Stop"
# 固定工作目录，避免从其他文件夹启动脚本时找不到源码与依赖清单。
Set-Location -LiteralPath $PSScriptRoot
python -c "import flet_cli, flet_desktop, PyInstaller"
if ($LASTEXITCODE -ne 0) {
    throw "Build dependencies are missing. Run: python -m pip install -r requirements-build.txt"
}
$normalizedVersion = $Version.Trim().TrimStart("v")
if ($normalizedVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must look like v0.0.0 or 0.0.0."
}
$env:READDRAW_VERSION = $normalizedVersion
# 发布版本必须与源码默认版本相同；环境变量不会自动写入冻结后的程序。
$sourceVersion = python -c "import os; os.environ.pop('READDRAW_VERSION', None); from readdraw.version import APP_VERSION; print(APP_VERSION)"
if ($LASTEXITCODE -ne 0 -or $sourceVersion.Trim() -ne $normalizedVersion) {
    throw "Release version does not match readdraw/version.py. Update APP_VERSION before building."
}
$scripts = python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
$flet = Join-Path $scripts.Trim() "flet.exe"
if (-not (Test-Path -LiteralPath $flet)) {
    $pythonFolder = python -c "import sys; print(f'Python{sys.version_info.major}{sys.version_info.minor}')"
    $flet = Join-Path $env:APPDATA "Python\$($pythonFolder.Trim())\Scripts\flet.exe"
}
if (-not (Test-Path -LiteralPath $flet)) {
    throw "Flet CLI was not found. Install dependencies with: python -m pip install -r requirements-build.txt"
}
$iconPath = Join-Path (Get-Location) "assets\ReadDraw.ico"
if (-not (Test-Path -LiteralPath $iconPath)) {
    throw "Application icon not found: $iconPath"
}
$arguments = @(
    "pack", "main.py", "--name", "ReadDraw", "--icon", $iconPath, "--distpath", "dist", "--yes",
    "--product-name", "ReadDraw", "--product-version", $normalizedVersion,
    "--file-version", "$normalizedVersion.0"
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
$releaseExe = Join-Path $releaseDirectory "ReadDraw.exe"
Copy-Item -LiteralPath $sourceExe -Destination $releaseExe -Force
$hash = (Get-FileHash -LiteralPath $releaseExe -Algorithm SHA256).Hash.ToLowerInvariant()
$shaPath = Join-Path $releaseDirectory "ReadDraw.exe.sha256"
"$hash  ReadDraw.exe" | Set-Content -LiteralPath $shaPath -Encoding ascii
$manifest = [ordered]@{
    version = $normalizedVersion
    tag = "v$normalizedVersion"
    product = "ReadDraw"
    platform = "windows-x64"
    asset = "ReadDraw.exe"
    sha256 = $hash
    release_url = "https://github.com/Chen-06-call/ReadDraw/releases/tag/v$normalizedVersion"
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releaseDirectory "update.json") -Encoding utf8
$makensis = Get-Command makensis.exe -ErrorAction SilentlyContinue
$nsisPath = if ($makensis) { $makensis.Source } else {
    # Chocolatey 安装 NSIS 后，当前 Actions 进程的 PATH 可能尚未刷新。
    @("${env:ProgramFiles(x86)}\NSIS\makensis.exe", "$env:ProgramFiles\NSIS\makensis.exe") |
        Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if ($RequireInstaller -and -not $nsisPath) {
    throw "NSIS was not found. Install NSIS before building the release."
}
if ($nsisPath) {
    $installerScript = Join-Path (Get-Location) "installer\ReadDraw.nsi"
    & $nsisPath "/DAPP_VERSION=$normalizedVersion" "/DEXE_PATH=$sourceExe" $installerScript
    if ($LASTEXITCODE -ne 0) {
        throw "NSIS installer build failed."
    }
} else {
    # 不允许保留旧安装包，以免和本次主程序版本不一致。
    Remove-Item -LiteralPath (Join-Path $releaseDirectory "ReadDraw-Setup.exe") -Force -ErrorAction SilentlyContinue
}
# 每次成功构建后移除按版本命名的旧产物，避免误传过期文件。
Get-ChildItem -LiteralPath $releaseDirectory -File |
    Where-Object { $_.Name -match '^ReadDraw-(Setup-v.+|v.+-windows-x64\.exe)(\.sha256)?$' } |
    Remove-Item -Force
Write-Host "ReadDraw package created: $sourceExe"
Write-Host "Release assets created under $releaseDirectory"
