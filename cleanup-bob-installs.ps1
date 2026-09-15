<#
.SYNOPSIS
    Remove duplicate or broken BOB installs without using Apps & Features (avoids Config.Msi errors).

.DESCRIPTION
    Finds BOB install folders on a drive, runs each folder's uninstall script, removes leftover
    directories, clears orphan Apps & Features registry entries, and optionally deletes
    Drive:\Config.Msi rollback files that cause MSI "Error: 5" during uninstall.

.PARAMETER Drive
    Drive letter or root path to search (e.g. I: or I:\BOBInstall). Defaults to all fixed drives.

.PARAMETER RemoveFolders
    Delete install folders after unregistering BOB. Default: $true.

.PARAMETER ClearConfigMsi
    Remove Config.Msi on searched drive(s). Default: $true when -Drive is set, else $false.

.PARAMETER ClearSetupCache
    Also remove %LOCALAPPDATA%\BOB\setup\payload-cache. Default: $false.

.PARAMETER RegistryOnly
    Skip folder scan/uninstall; only remove BOB from Apps & Features and MSI registry.

.PARAMETER Force
    Skip confirmation prompts.

.PARAMETER WhatIf
    Show what would be removed without making changes.

.EXAMPLE
    .\cleanup-bob-installs.ps1 -Drive I:

.EXAMPLE
    .\cleanup-bob-installs.ps1 -Drive I: -Force
#>
param(
    [string]$Drive = "",
    [bool]$RemoveFolders = $true,
    [Nullable[bool]]$ClearConfigMsi = $null,
    [bool]$ClearSetupCache = $false,
    [switch]$RegistryOnly,
    [switch]$Force,
    [switch]$WhatIf
)

# Bob.msi UpgradeCode from installer/wix/Variables.wxi
$BobMsiUpgradeCode = "8F3C1A7E-6B2D-4E91-9C4A-2D8F7B1E5A30"

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Detail([string]$Message) {
    Write-Host "    $Message"
}

function Get-SearchRoots {
    param([string]$DriveFilter)
    if ($DriveFilter) {
        $root = $DriveFilter.TrimEnd('\')
        if (-not $root.EndsWith(':')) { $root = Split-Path $root -Qualifier }
        if (-not $root) { throw "Could not parse drive from: $DriveFilter" }
        return @($root + '\')
    }
    $roots = @()
    foreach ($vol in [System.IO.DriveInfo]::GetDrives()) {
        if ($vol.DriveType -eq 'Fixed' -and $vol.IsReady) {
            $roots += $vol.Name
        }
    }
    return $roots
}

function Test-BobInstallRoot([string]$Path) {
    if (-not $Path) { return $false }
    return (Test-Path (Join-Path $Path "bob\__main__.py")) -and
        (Test-Path (Join-Path $Path "packaging\setup_wizard.py"))
}

function Find-BobInstallRoots {
    param([string[]]$SearchRoots)

    $found = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)

    $bobKey = "HKCU:\Software\Bob"
    if (Test-Path $bobKey) {
        $props = Get-ItemProperty $bobKey -ErrorAction SilentlyContinue
        if ($props.InstallFolder -and (Test-BobInstallRoot $props.InstallFolder)) {
            [void]$found.Add($props.InstallFolder.TrimEnd('\'))
        }
    }

    $uninstallRoot = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
    if (Test-Path $uninstallRoot) {
        Get-ChildItem $uninstallRoot -ErrorAction SilentlyContinue | ForEach-Object {
            $props = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            if (-not $props.DisplayName) { return }
            if ($props.DisplayName -notlike "*BOB*") { return }
            foreach ($candidate in @($props.InstallLocation, $props.InstallSource)) {
                if (-not $candidate) { continue }
                $dir = $candidate.TrimEnd('\')
                if (Test-BobInstallRoot $dir) {
                    [void]$found.Add($dir)
                }
            }
        }
    }

    foreach ($searchRoot in $SearchRoots) {
        if (-not (Test-Path $searchRoot)) { continue }
        Get-ChildItem $searchRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            if (Test-BobInstallRoot $_.FullName) {
                [void]$found.Add($_.FullName)
            }
        }
    }

    return @($found) | Sort-Object
}

function Stop-BobAndMsi {
    $stopScript = Join-Path $PSScriptRoot "stop_bob.ps1"
    if (Test-Path $stopScript) {
        . $stopScript
        foreach ($root in $script:InstallRoots) {
            Stop-BobInstances -ProjectRoot $root | Out-Null
        }
    }

    Get-Process msiexec -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Detail "Stopping msiexec (PID $($_.Id))..."
        if (-not $WhatIf) {
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Milliseconds 500
}

function Invoke-BobFolderUninstall {
    param([string]$InstallRoot)

    Write-Detail "Unregistering BOB at $InstallRoot"
    if ($WhatIf) { return }

    $uninstallPs1 = Join-Path $InstallRoot "uninstall.ps1"
    $venvPython = Join-Path $InstallRoot ".venv\Scripts\python.exe"
    $msiPost = Join-Path $InstallRoot "packaging\msi_postinstall.py"
    $installPy = Join-Path $InstallRoot "packaging\install.py"

    if (Test-Path $uninstallPs1) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uninstallPs1
        return
    }
    if ((Test-Path $venvPython) -and (Test-Path $msiPost)) {
        & $venvPython $msiPost --root $InstallRoot --uninstall
        return
    }
    if ((Test-Path $venvPython) -and (Test-Path $installPy)) {
        & $venvPython $installPy --uninstall
        return
    }

    Write-Detail "No uninstall helper found; registry cleanup only."
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-BobUninstallEntry {
    param($Properties)
    if (-not $Properties) { return $false }
    $name = [string]$Properties.DisplayName
    $publisher = [string]$Properties.Publisher
    if ($name -match '^\s*BOB\s*$') { return $true }
    if ($publisher -match '^\s*BOB\s*$' -and $name -like '*BOB*') { return $true }
    return $false
}

function Get-MsiCompressedGuid {
    param([string]$Guid)
    $g = $Guid.Trim('{}').Replace('-', '')
    if ($g.Length -ne 32) { return $null }
    return (
        $g.Substring(6, 2) + $g.Substring(4, 2) + $g.Substring(2, 2) + $g.Substring(0, 2) +
        $g.Substring(10, 2) + $g.Substring(8, 2) +
        $g.Substring(14, 2) + $g.Substring(12, 2) +
        $g.Substring(16)
    )
}

function Remove-RegistryKeySafe {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Write-Detail "Removing $Path"
    if ($WhatIf) { return }
    try {
        Remove-Item $Path -Recurse -Force -ErrorAction Stop
    }
    catch {
        Write-Host "    Failed: $($_.Exception.Message)" -ForegroundColor Yellow
        $script:RegistryCleanupErrors++
    }
}

function Get-BobMsiProductCodes {
    $codes = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $uninstallRoots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    foreach ($uninstallRoot in $uninstallRoots) {
        if (-not (Test-Path $uninstallRoot)) { continue }
        Get-ChildItem $uninstallRoot -ErrorAction SilentlyContinue | ForEach-Object {
            $props = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            if (-not (Test-BobUninstallEntry $props)) { return }
            $id = $_.PSChildName
            if ($id -match '^\{[0-9A-Fa-f-]{36}\}$') {
                [void]$codes.Add($id)
            }
        }
    }
    return @($codes)
}

function Remove-BobMsiRegistry {
    param([string[]]$ProductCodes)

    $hives = @("HKCU", "HKLM")
    foreach ($productCode in $ProductCodes) {
        $compressed = Get-MsiCompressedGuid $productCode
        foreach ($hive in $hives) {
            Remove-RegistryKeySafe "$hive`:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$productCode"
            if ($compressed) {
                Remove-RegistryKeySafe "$hive`:\Software\Microsoft\Installer\Products\$compressed"
                Remove-RegistryKeySafe "$hive`:\Software\Classes\Installer\Products\$compressed"
                Remove-RegistryKeySafe "$hive`:\Software\Microsoft\Installer\Features\$compressed"
            }
        }
    }

    $upgradeCompressed = Get-MsiCompressedGuid $BobMsiUpgradeCode
    foreach ($hive in $hives) {
        $upgradePath = "$hive`:\Software\Microsoft\Installer\UpgradeCodes\$upgradeCompressed"
        if (Test-Path $upgradePath) {
            Remove-RegistryKeySafe $upgradePath
        }
    }
}

function Remove-BobRegistryEntries {
    $script:RegistryCleanupErrors = 0
    $productCodes = Get-BobMsiProductCodes
    Write-Detail "MSI product codes found: $($productCodes.Count)"
    foreach ($code in $productCodes) {
        Write-Detail "  $code"
    }

    $needsAdmin = $false
    foreach ($code in $productCodes) {
        if (Test-Path "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$code") {
            $needsAdmin = $true
            break
        }
    }
    if ($needsAdmin -and -not (Test-IsAdministrator)) {
        Write-Host ""
        Write-Host "BOB is registered under HKLM (machine-wide). Re-run this script in an elevated PowerShell:" -ForegroundColor Yellow
        Write-Host "  Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -RegistryOnly -Force'" -ForegroundColor Yellow
        Write-Host ""
    }

    $keys = @(
        "HKCU:\Software\Bob",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Bob",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\Bob.exe",
        "HKCU:\Software\Classes\Applications\Bob.exe",
        "HKCU:\Software\Classes\AppUserModelId\Cash.Bob"
    )
    foreach ($key in $keys) {
        Remove-RegistryKeySafe $key
    }

    $uninstallRoots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    foreach ($uninstallRoot in $uninstallRoots) {
        if (-not (Test-Path $uninstallRoot)) { continue }
        Get-ChildItem $uninstallRoot -ErrorAction SilentlyContinue | ForEach-Object {
            $props = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            if (Test-BobUninstallEntry $props) {
                Remove-RegistryKeySafe $_.PSPath
            }
        }
    }

    Remove-BobMsiRegistry -ProductCodes $productCodes

    if ($script:RegistryCleanupErrors -gt 0) {
        Write-Host "Some registry keys could not be removed. Use elevated PowerShell and retry -RegistryOnly." -ForegroundColor Yellow
    }
}

function Clear-DriveConfigMsi {
    param([string[]]$SearchRoots)

    foreach ($searchRoot in $SearchRoots) {
        $drive = Split-Path $searchRoot -Qualifier
        if (-not $drive) { continue }
        $configMsi = Join-Path $drive "Config.Msi"
        if (-not (Test-Path $configMsi)) { continue }

        Write-Detail "Removing $configMsi"
        if ($WhatIf) { continue }

        try {
            Remove-Item $configMsi -Recurse -Force -ErrorAction Stop
        }
        catch {
            Write-Host "    Could not remove $configMsi ($($_.Exception.Message))." -ForegroundColor Yellow
            Write-Host "    Try an elevated PowerShell:" -ForegroundColor Yellow
            Write-Host "      takeown /f $configMsi /r /d y" -ForegroundColor Yellow
            Write-Host "      icacls $configMsi /grant $($env:USERNAME):(F) /t" -ForegroundColor Yellow
            Write-Host "      Remove-Item -Recurse -Force $configMsi" -ForegroundColor Yellow
        }
    }
}

function Clear-SetupPayloadCache {
    $cache = Join-Path $env:LOCALAPPDATA "BOB\setup\payload-cache"
    if (-not (Test-Path $cache)) { return }
    Write-Detail "Removing $cache"
    if (-not $WhatIf) {
        Remove-Item $cache -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$searchRoots = Get-SearchRoots -DriveFilter $Drive
if ($null -eq $ClearConfigMsi) {
    $ClearConfigMsi = [bool]$Drive
}

if ($RegistryOnly) {
    $script:InstallRoots = @()
    $RemoveFolders = $false
    $ClearConfigMsi = $false
}
else {
    $script:InstallRoots = Find-BobInstallRoots -SearchRoots $searchRoots
}

Write-Step "BOB install cleanup"
if (-not $RegistryOnly) {
    Write-Detail "Search roots: $($searchRoots -join ', ')"
    Write-Detail "Install folders found: $($script:InstallRoots.Count)"
    foreach ($root in $script:InstallRoots) {
        Write-Detail "  $root"
    }
}
else {
    Write-Detail "Registry-only mode (Apps & Features / MSI cleanup)"
}

if (-not $Force -and -not $WhatIf) {
    Write-Host ""
    $prompt = if ($RegistryOnly) {
        "Remove all BOB entries from Apps & Features and MSI registry"
    } else {
        "Remove $($script:InstallRoots.Count) BOB install(s) and clean registry"
    }
    if ($RemoveFolders) { $prompt += " (delete folders)" }
    if ($ClearConfigMsi) { $prompt += " (clear Config.Msi)" }
    $prompt += "? [y/N] "
    $answer = Read-Host $prompt
    if ($answer -notmatch '^[yY]') {
        Write-Host "Cancelled."
        exit 0
    }
}

if (-not $RegistryOnly) {
    Write-Step "Stopping BOB and Windows Installer"
    Stop-BobAndMsi

    Write-Step "Unregistering each install folder"
    foreach ($root in $script:InstallRoots) {
        Invoke-BobFolderUninstall -InstallRoot $root
    }

    if ($RemoveFolders) {
        Write-Step "Removing install folders"
        foreach ($root in $script:InstallRoots) {
            if (-not (Test-Path $root)) { continue }
            Write-Detail "Deleting $root"
            if (-not $WhatIf) {
                Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

Write-Step "Cleaning registry entries"
Remove-BobRegistryEntries

if ($ClearConfigMsi) {
    Write-Step "Clearing Config.Msi rollback folders"
    Clear-DriveConfigMsi -SearchRoots $searchRoots
}

if ($ClearSetupCache) {
    Write-Step "Clearing installer payload cache"
    Clear-SetupPayloadCache
}

Write-Step "Done"
if ($WhatIf) {
    Write-Host "WhatIf mode: no changes were made." -ForegroundColor Yellow
}
else {
    Write-Host "BOB cleanup finished. Reboot if Apps & Features still shows stale entries."
}
