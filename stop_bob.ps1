param(
    [string]$ProjectRoot = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

function Stop-BobInstances {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $root = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd('\')
    $venvScripts = Join-Path $root ".venv\Scripts"
    $processNames = @("python.exe", "pythonw.exe", "Bob.exe")
    $stopped = 0

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $processNames -contains $_.Name } |
        ForEach-Object {
            $exe = $_.ExecutablePath
            $cmd = $_.CommandLine
            $fromVenv = $exe -and $exe.StartsWith($venvScripts, [System.StringComparison]::OrdinalIgnoreCase)

            if ($_.Name -eq "Bob.exe") {
                if (-not $fromVenv) { return }
            }
            else {
                if (-not $cmd -or $cmd -notmatch '-m\s+bob\b') { return }
                if (-not $fromVenv -and $cmd -notlike "*$root*") { return }
            }

            Write-Host "Stopping Bob (PID $($_.ProcessId))..."
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $stopped++
        }

    if ($stopped -gt 0) {
        Start-Sleep -Milliseconds 750
    }

    return $stopped
}

if ($MyInvocation.InvocationName -ne '.') {
    Stop-BobInstances -ProjectRoot $ProjectRoot | Out-Null
}
