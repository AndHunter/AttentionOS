param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$Root\build"
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$Root\dist"
}

python -m pip install -e ".[build]"

python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name AttentionOS `
    --exclude-module pandas `
    --exclude-module numpy `
    --exclude-module scipy `
    --exclude-module sklearn `
    --exclude-module catboost `
    --exclude-module torch `
    --exclude-module torchvision `
    --exclude-module torchaudio `
    --exclude-module streamlit `
    --exclude-module plotly `
    --exclude-module pytest `
    --exclude-module IPython `
    --collect-data attentionos.localization `
    --paths "$Root\src" `
    "$Root\src\attentionos\desktop\app.py"

Write-Host "Built $Root\dist\AttentionOS.exe"
