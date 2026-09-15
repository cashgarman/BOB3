$ErrorActionPreference = "Stop"
$InstallerRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Split-Path -Parent $InstallerRoot
$PayloadDir = Join-Path $InstallerRoot "payload"
$OutDir = Join-Path $InstallerRoot "out"
$WixDir = Join-Path $InstallerRoot "wix"
$Csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

function Find-WiX {
    $candidates = @(
        ${env:WIX},
        "C:\Program Files (x86)\WiX Toolset v3.14\bin",
        "C:\Program Files (x86)\WiX Toolset v3.11\bin",
        "C:\Program Files\WiX Toolset v3.14\bin"
    ) | Where-Object { $_ }
    foreach ($dir in $candidates) {
        $candle = Join-Path $dir "candle.exe"
        if (Test-Path $candle) { return $dir }
    }
    $cmd = Get-Command candle.exe -ErrorAction SilentlyContinue
    if ($cmd) { return Split-Path $cmd.Source }
    return $null
}

function Invoke-Csc([string[]]$CscArgs) {
    if (-not (Test-Path $Csc)) { throw "C# compiler not found: $Csc" }
    & $Csc @CscArgs
    if ($LASTEXITCODE -ne 0) { throw "csc failed: $($CscArgs -join ' ')" }
}

$wixBin = Find-WiX
if (-not $wixBin) {
    Write-Host ""
    Write-Host "WiX Toolset 3.14+ is required (candle.exe / light.exe / heat.exe)." -ForegroundColor Red
    Write-Host ""
    Write-Host "Install (run PowerShell as Administrator):" -ForegroundColor Yellow
    Write-Host "  winget install --id WiXToolset.WiXToolset -e"
    Write-Host ""
    Write-Host "WiX 3.14 also needs .NET Framework 3.5 (NetFx3). If winget prompts for it, enable"
    Write-Host "  'Turn Windows features on or off' -> .NET Framework 3.5"
    Write-Host ""
    Write-Host "After install, open a new terminal (or set WIX to the bin folder), then rerun:"
    Write-Host "  .\installer\scripts\build.ps1"
    Write-Host ""
    Write-Host "Manual download: https://wixtoolset.org/releases/"
    throw "WiX Toolset not found."
}
Write-Host "Using WiX at $wixBin"

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Build needs the project .venv. Run setup.ps1 first."
}

Write-Host "Staging payload…"
if (Test-Path $PayloadDir) { Remove-Item $PayloadDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $PayloadDir, $OutDir | Out-Null

$copyDirs = @("bob", "packaging", "prompts")
foreach ($name in $copyDirs) {
    Copy-Item (Join-Path $RepoRoot $name) (Join-Path $PayloadDir $name) -Recurse -Force
}
foreach ($name in @("run.ps1", "stop_bob.ps1", "uninstall.ps1", "cleanup-bob-installs.ps1", "requirements.txt", "pyproject.toml")) {
    Copy-Item (Join-Path $RepoRoot $name) (Join-Path $PayloadDir $name) -Force
}
Copy-Item (Join-Path $InstallerRoot "config.defaults.yaml") (Join-Path $PayloadDir "config.yaml") -Force
Copy-Item (Join-Path $InstallerRoot "runtime-deps.json") (Join-Path $PayloadDir "runtime-deps.json") -Force
New-Item -ItemType Directory -Force -Path (Join-Path $PayloadDir "models"), (Join-Path $PayloadDir "data") | Out-Null
Get-ChildItem $PayloadDir -Recurse -Include "__pycache__", "*.pyc" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
# Remove build-time-only exes from payload; post-install rebuilds Bob.exe locally.
Get-ChildItem $PayloadDir -Recurse -Filter "*.exe" | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host "Generating icon and logo…"
$icon = Join-Path $PayloadDir "packaging\bob.ico"
$logo = Join-Path $InstallerRoot "assets\logo.png"
& $python -c @"
from pathlib import Path
import sys
sys.path.insert(0, r'$RepoRoot')
sys.path.insert(0, r'$RepoRoot\packaging')
from windows_install import write_icon, write_logo_png
write_icon(Path(r'$icon'))
write_logo_png(Path(r'$logo'), 128)
write_logo_png(Path(r'$OutDir\logo.png'), 256)
print('icon ok')
"@
Copy-Item (Join-Path $InstallerRoot "assets\license.rtf") (Join-Path $OutDir "license.rtf") -Force

Write-Host "Compiling native helpers…"
$fx = Split-Path $Csc
Invoke-Csc @(
    "/nologo", "/optimize", "/target:winexe", "/platform:x64",
    "/reference:$fx\System.Windows.Forms.dll",
    "/reference:$fx\System.Drawing.dll",
    "/out:$OutDir\InstallOllama.exe",
    "$RepoRoot\packaging\install_ollama.cs"
)
Invoke-Csc @(
    "/nologo", "/optimize", "/target:winexe", "/platform:x64",
    "/reference:$fx\System.Windows.Forms.dll",
    "/reference:$fx\System.Drawing.dll",
    "/out:$PayloadDir\packaging\progress_host.exe",
    "$RepoRoot\packaging\progress_host.cs"
)
Invoke-Csc @(
    "/nologo", "/optimize", "/target:exe", "/platform:x64",
    "/out:$OutDir\RunPostInstall.exe",
    "$RepoRoot\packaging\run_postinstall.cs"
)
Invoke-Csc @(
    "/nologo", "/optimize", "/target:winexe", "/platform:x64",
    "/reference:$fx\System.Windows.Forms.dll",
    "/reference:$fx\System.Drawing.dll",
    "/reference:$fx\System.Management.dll",
    "/out:$OutDir\LaunchSetupWizard.exe",
    "$RepoRoot\packaging\launch_setup_wizard.cs"
)
$setupStub = Join-Path $OutDir "BobSetup.stub.exe"
Invoke-Csc @(
    "/nologo", "/optimize", "/target:winexe", "/platform:x64",
    "/reference:$fx\System.Windows.Forms.dll",
    "/reference:$fx\System.Drawing.dll",
    "/reference:$fx\System.Web.Extensions.dll",
    "/out:$setupStub",
    "$RepoRoot\packaging\embedded_payload.cs",
    "$RepoRoot\packaging\existing_installs.cs",
    "$RepoRoot\packaging\bob_setup_ui.cs"
)

Write-Host "Harvesting payload with heat…"
$heat = Join-Path $wixBin "heat.exe"
$candle = Join-Path $wixBin "candle.exe"
$light = Join-Path $wixBin "light.exe"
$payloadWxs = Join-Path $WixDir "Payload.wxs"
& $heat dir $PayloadDir -nologo -cg PayloadComponents -gg -scom -sreg -sfrag -srd -ke -dr INSTALLFOLDER -var var.PayloadDir -out $payloadWxs
if ($LASTEXITCODE -ne 0) { throw "heat failed" }
& $python (Join-Path $InstallerRoot "scripts\fix-payload-ice64.py") $payloadWxs
if ($LASTEXITCODE -ne 0) { throw "fix-payload-ice64 failed" }

Write-Host "Building Bob.msi…"
$wixObj = Join-Path $OutDir "wixobj"
New-Item -ItemType Directory -Force -Path $wixObj | Out-Null
& $candle -nologo -arch x64 -ext WixUtilExtension `
    "-dPayloadDir=$PayloadDir" `
    -o "$wixObj\" `
    (Join-Path $WixDir "Product.wxs"), $payloadWxs
if ($LASTEXITCODE -ne 0) { throw "candle (msi) failed" }
& $light -nologo -ext WixUtilExtension -spdb `
    -sice:ICE38 -sice:ICE43 -sice:ICE57 -sice:ICE64 -sice:ICE91 `
    -o (Join-Path $OutDir "Bob.msi") `
    (Join-Path $wixObj "Product.wixobj"), (Join-Path $wixObj "Payload.wixobj")
if ($LASTEXITCODE -ne 0) { throw "light (msi) failed" }

Write-Host "Packing single-file installer…"
$packScript = Join-Path $RepoRoot "packaging\pack_bob_setup.py"
$payloadFiles = @(
    (Join-Path $OutDir "Bob.msi"),
    (Join-Path $OutDir "InstallOllama.exe"),
    (Join-Path $OutDir "RunPostInstall.exe"),
    (Join-Path $OutDir "logo.png"),
    (Join-Path $OutDir "license.rtf")
)
& $python $packScript $setupStub (Join-Path $OutDir "BobSetup.exe") @payloadFiles
if ($LASTEXITCODE -ne 0) { throw "pack_bob_setup failed" }
Remove-Item $setupStub -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Build complete (Bob source only; Python packages download on the target PC)."
Write-Host "  MSI:         $(Join-Path $OutDir 'Bob.msi')"
Write-Host "  Installer:   $(Join-Path $OutDir 'BobSetup.exe')  (single-file; distribute this alone)"
