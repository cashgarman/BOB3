$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "No .venv found. Run .\setup.ps1 first."
    exit 1
}

& $python (Join-Path $PSScriptRoot "packaging\install.py") @args
exit $LASTEXITCODE
