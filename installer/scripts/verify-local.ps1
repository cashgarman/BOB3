$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Run setup.ps1 first so tests can execute." }

Write-Host "Running installer unit tests…"
& $python -m pytest tests/test_llm_recommend.py tests/test_ollama_pull.py tests/test_bootstrap_models.py tests/test_setup_wizard.py tests/test_installer_wix.py tests/test_msi_postinstall.py tests/test_pip_with_progress.py tests/test_settings.py tests/test_util_hotkeys.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (Test-Path $csc) {
    $fx = Split-Path $csc
    $tmp = Join-Path $env:TEMP "bob-installer-compile"
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    Write-Host "Compiling progress_host.cs, install_ollama.cs, run_postinstall.cs, and launch_setup_wizard.cs…"
    & $csc /nologo /t:winexe /platform:x64 /r:"$fx\System.Windows.Forms.dll" /r:"$fx\System.Drawing.dll" /out:"$tmp\progress_host.exe" "$RepoRoot\packaging\progress_host.cs"
    if ($LASTEXITCODE -ne 0) { throw "progress_host.cs failed to compile" }
    & $csc /nologo /t:winexe /platform:x64 /r:"$fx\System.Windows.Forms.dll" /r:"$fx\System.Drawing.dll" /out:"$tmp\InstallOllama.exe" "$RepoRoot\packaging\install_ollama.cs"
    if ($LASTEXITCODE -ne 0) { throw "install_ollama.cs failed to compile" }
    & $csc /nologo /t:exe /platform:x64 /out:"$tmp\RunPostInstall.exe" "$RepoRoot\packaging\run_postinstall.cs"
    if ($LASTEXITCODE -ne 0) { throw "run_postinstall.cs failed to compile" }
    & $csc /nologo /t:winexe /platform:x64 /r:"$fx\System.Windows.Forms.dll" /r:"$fx\System.Drawing.dll" /out:"$tmp\BobSetup.exe" "$RepoRoot\packaging\bob_setup_ui.cs"
    if ($LASTEXITCODE -ne 0) { throw "bob_setup_ui.cs failed to compile" }
    & $csc /nologo /t:winexe /platform:x64 /r:"$fx\System.Windows.Forms.dll" /r:"$fx\System.Management.dll" /out:"$tmp\LaunchSetupWizard.exe" "$RepoRoot\packaging\launch_setup_wizard.cs"
    if ($LASTEXITCODE -ne 0) { throw "launch_setup_wizard.cs failed to compile" }
    Write-Host "C# helpers compiled."
} else {
    Write-Host "csc.exe not found; skipped native helper compile."
}

$wix = @(
    ${env:WIX},
    "C:\Program Files (x86)\WiX Toolset v3.14\bin",
    "C:\Program Files (x86)\WiX Toolset v3.11\bin"
) | Where-Object { $_ -and (Test-Path (Join-Path $_ "candle.exe")) } | Select-Object -First 1
if ($wix) {
    Write-Host "WiX found at $wix (full bundle build needs .\installer\scripts\build.ps1)."
} else {
    Write-Host "WiX Toolset not installed; skipped candle/light. Install WiX 3.14 to build BobSetup.exe."
}

Write-Host "Local installer verification passed."
