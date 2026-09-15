param(
    [Parameter(Mandatory = $true)][string]$InstallFolder,
    [int]$DesktopShortcut = 0,
    [switch]$Desktop,
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"

function Get-CancelPath {
    if ($env:BOB_INSTALL_CANCEL) { return $env:BOB_INSTALL_CANCEL }
    return Join-Path $env:TEMP "bob-install.cancel"
}

function Test-InstallCancelled {
    if (Test-Path (Get-CancelPath)) { exit 2 }
}

function Test-VenvReady {
    param([string]$Root)
    $cfg = Join-Path $Root ".venv\pyvenv.cfg"
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not ((Test-Path $cfg) -and (Test-Path $py))) { return $false }
    & $py -c "import sys" 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Remove-BrokenVenv {
    param([string]$Root)
    $venv = Join-Path $Root ".venv"
    if ((Test-Path $venv) -and -not (Test-VenvReady $Root)) {
        Remove-Item $venv -Recurse -Force
    }
}

function Get-InstallLogPath {
    if ($env:BOB_INSTALL_LOG) { return $env:BOB_INSTALL_LOG }
    return Join-Path $env:TEMP "bob-install.log"
}

function Write-InstallLog {
    param([string]$Line)
    if (-not $Line) { return }
    Add-Content -Path (Get-InstallLogPath) -Value $Line -Encoding utf8
}

function Ensure-InstallFiles {
    param([string]$Root)
    $req = Join-Path $Root "requirements.txt"
    if (-not (Test-Path $req)) {
        throw "Bob install files are missing. Remove `"$Root`" and run BobSetup.exe again."
    }
}
# MSI passes INSTALLFOLDER with a trailing backslash; never quote that value on the command line
# (a trailing \" escapes the closing quote and breaks path parsing).
$InstallFolder = $InstallFolder.Trim().Trim('"').TrimEnd('\')
if ($DesktopShortcut -eq 1) { $Desktop = $true }

$progress = Join-Path $InstallFolder "packaging\progress_host.exe"
$progressProc = $null
if ((Test-Path $progress) -and -not $Uninstall -and -not $env:BOB_SETUP_UI) {
    $progressProc = Start-Process -FilePath $progress -PassThru
}

try {
    $venvPy = Join-Path $InstallFolder ".venv\Scripts\python.exe"
    $embedPy = Join-Path $InstallFolder "python\python.exe"
    $script = Join-Path $InstallFolder "packaging\msi_postinstall.py"
    $downloadScript = Join-Path $InstallFolder "packaging\download_runtime.ps1"
    $manifest = Join-Path $InstallFolder "runtime-deps.json"
    $desktopArg = @()
    if ($Desktop) { $desktopArg = @("--desktop") }

    if ($Uninstall) {
        $py = if (Test-Path $venvPy) { $venvPy } elseif (Test-Path $embedPy) { $embedPy } else { $null }
        if ($py) {
            & $py $script --root $InstallFolder --uninstall
        }
        exit 0
    }

    $env:BOB_ROOT = $InstallFolder
    Set-Location $InstallFolder
    Ensure-InstallFiles -Root $InstallFolder
    Remove-BrokenVenv -Root $InstallFolder

    if (-not (Test-VenvReady $InstallFolder)) {
        if (-not (Test-Path $downloadScript)) { throw "download_runtime.ps1 is missing from the install folder" }
        try {
            Write-InstallLog "> powershell -File $downloadScript -InstallFolder $InstallFolder"
            & $downloadScript -InstallFolder $InstallFolder -ManifestPath $manifest
        } catch {
            if (Test-Path (Get-CancelPath)) { exit 2 }
            throw
        }
        Test-InstallCancelled
        $embedPy = Join-Path $InstallFolder "python\python.exe"
    }

    $runner = if (Test-VenvReady $InstallFolder) { $venvPy } elseif (Test-Path $embedPy) { $embedPy } else { $null }
    if (-not $runner) { throw "Python 3.12 could not be installed or found on this PC" }
    Test-InstallCancelled
    $desktopSuffix = if ($Desktop) { " --desktop" } else { "" }
    Write-InstallLog "> $runner $script --root $InstallFolder$desktopSuffix"
    & $runner $script --root $InstallFolder @desktopArg
    if ($LASTEXITCODE -eq 2) { exit 2 }
    if ($LASTEXITCODE -ne 0) {
        Write-InstallLog "  exited $LASTEXITCODE"
        throw "BOB post-install failed with exit code $LASTEXITCODE"
    }
    Write-InstallLog "  done"
} catch {
    if (Test-Path (Get-CancelPath)) { exit 2 }
    throw
}
finally {
    if ($progressProc -and -not $progressProc.HasExited) {
        Start-Sleep -Milliseconds 400
        try { $progressProc.CloseMainWindow() | Out-Null } catch {}
        Start-Sleep -Milliseconds 200
        if (-not $progressProc.HasExited) { Stop-Process -Id $progressProc.Id -Force -ErrorAction SilentlyContinue }
    }
}
