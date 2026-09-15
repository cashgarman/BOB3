$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $python) {
    & $python -c "from bob.startup import disable; disable()"
    & $python (Join-Path $PSScriptRoot "packaging\install.py") --uninstall
    exit $LASTEXITCODE
}

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Bob.lnk"
$desktop = Join-Path $env:USERPROFILE "Desktop\Bob.lnk"
foreach ($lnk in @($startMenu, $desktop)) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
}
$keys = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Bob",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\Bob.exe",
    "HKCU:\Software\Classes\Applications\Bob.exe",
    "HKCU:\Software\Classes\AppUserModelId\Cash.Bob"
)
foreach ($key in $keys) {
    if (Test-Path $key) { Remove-Item $key -Recurse -Force }
}
Write-Host "Bob was removed from the Start Menu and Apps list."
