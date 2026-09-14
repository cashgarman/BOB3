$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating Python 3.12 virtualenv in .venv ..."
    py -3.12 -m venv .venv
    if (-not $?) { throw "Python 3.12 is required (py -3.12). System 3.14 cannot install CUDA Whisper wheels." }
} else {
    Write-Host "Using existing .venv"
    $ver = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($ver -ne "3.12") { throw "Existing .venv is Python $ver; delete it and rerun setup.ps1 (need 3.12)." }
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# --isolated ignores the machine pip extra-index (pypi.ngc.nvidia.com), which times out here.
& $python -m pip install --isolated -U pip wheel --index-url https://pypi.org/simple
& $python -m pip install --isolated -r (Join-Path $PSScriptRoot "requirements.txt") --index-url https://pypi.org/simple
& $python -m pip install --isolated -e $PSScriptRoot --index-url https://pypi.org/simple

Write-Host ""
Write-Host "Setup complete."
Write-Host "Run:  .\run.ps1"
Write-Host "Check: .\.venv\Scripts\python.exe -m bob --check"
