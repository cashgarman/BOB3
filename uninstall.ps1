$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "No .venv found. Bob's Windows app registration will still be removed."
}

if (Test-Path $python) {
    & $python (Join-Path $PSScriptRoot "packaging\install.py") --uninstall
    exit $LASTEXITCODE
}

Write-Host "Python venv missing; skipping branded exe cleanup."
