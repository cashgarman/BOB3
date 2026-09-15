$paths = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKCU:\Software\Microsoft\Installer\Products',
    'HKCU:\Software\Microsoft\Installer\UpgradeCodes',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
)
foreach ($root in $paths) {
    if (-not (Test-Path $root)) { continue }
    Write-Host "=== $root ===" -ForegroundColor Cyan
    Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
        $props = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
        $name = $props.DisplayName
        $pub = $props.Publisher
        $loc = $props.InstallLocation
        if ($name -match 'bob' -or $pub -match 'bob' -or $_.PSChildName -match 'bob') {
            Write-Host "$($_.PSChildName) | $name | $pub | $loc"
        }
    }
}
