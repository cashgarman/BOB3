param(
    [string]$InstallFolder,
    [string]$ManifestPath
)
$ErrorActionPreference = "Stop"

function Get-CancelPath {
    if ($env:BOB_INSTALL_CANCEL) { return $env:BOB_INSTALL_CANCEL }
    return Join-Path $env:TEMP "bob-install.cancel"
}

function Test-InstallCancelled {
    if (Test-Path (Get-CancelPath)) {
        throw "Installation cancelled."
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

function Write-InstallProgress {
    param(
        [string]$Phase,
        [string]$Message,
        [double]$Overall = 0,
        [double]$Stage = 0,
        [long]$Completed = 0,
        [long]$Total = 0,
        [double]$StepEtaSeconds = 0,
        [double]$StepDurationSeconds = 900,
        [double]$RateBps = 0
    )
    $path = if ($env:BOB_INSTALL_PROGRESS) { $env:BOB_INSTALL_PROGRESS } else { Join-Path $env:TEMP "bob-install.json" }
    $payload = @{
        phase = $Phase
        message = $Message
        overall = [Math]::Max(0, [Math]::Min(1, $Overall))
        stage = [Math]::Max(0, [Math]::Min(1, $Stage))
        completed = if ($Completed) { $Completed } else { $null }
        total = if ($Total) { $Total } else { $null }
        rate_bps = if ($RateBps) { $RateBps } else { $null }
        eta_seconds = if ($StepEtaSeconds) { $StepEtaSeconds } else { $null }
        step_eta_seconds = if ($StepEtaSeconds) { $StepEtaSeconds } else { $null }
        step_duration_seconds = $StepDurationSeconds
        step = 3
        step_total = 11
        done = $false
    } | ConvertTo-Json -Compress
    Set-Content -Path $path -Value $payload -Encoding utf8
}

function Download-FileWithProgress {
    param(
        [string]$Url,
        [string]$Destination,
        [string]$Message,
        [double]$Overall = 0.08,
        [double]$OverallSpan = 0.04
    )
    $request = [System.Net.HttpWebRequest]::Create($Url)
    $request.UserAgent = "BOB-Installer"
    $request.Timeout = 600000
    $response = $request.GetResponse()
    $total = [int64]$response.ContentLength
    $stream = $response.GetResponseStream()
    $file = [System.IO.File]::Create($Destination)
    $buffer = New-Object byte[] 262144
    $done = [int64]0
    $started = Get-Date
    try {
        while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            Test-InstallCancelled
            $file.Write($buffer, 0, $read)
            $done += $read
            $elapsed = [Math]::Max(((Get-Date) - $started).TotalSeconds, 0.001)
            $rate = $done / $elapsed
            $stage = if ($total -gt 0) { $done / $total } else { 0 }
            $eta = if ($total -gt $done -and $rate -gt 0) { ($total - $done) / $rate } else { 0 }
            $overallPos = $Overall + ($OverallSpan * $stage)
            Write-InstallProgress -Phase "python" -Message $Message -Overall $overallPos -Stage $stage `
                -Completed $done -Total $total -StepEtaSeconds $eta -RateBps $rate -StepDurationSeconds 120
        }
    }
    finally {
        $file.Close()
        $stream.Close()
        $response.Close()
    }
}

function Get-RuntimeManifest {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Runtime dependency manifest not found: $Path"
    }
    return Get-Content $Path -Raw | ConvertFrom-Json
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

function Test-PythonReady {
    param([string]$Root)
    if (Test-VenvReady $Root) { return $true }
    $embed = Join-Path $Root "python\python.exe"
    return (Test-Path $embed) -and (Test-Python312Exe $embed)
}

function Test-Python312Exe {
    param([string]$Exe)
    if (-not $Exe -or -not (Test-Path $Exe)) { return $false }
    $ver = & $Exe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    return $ver -eq "3.12"
}

function Get-SystemPython312 {
    foreach ($exe in (Get-Python312Candidates)) {
        if (Test-Python312Exe $exe) { return $exe }
    }
    return $null
}

function Get-Python312Candidates {
    $seen = New-Object 'System.Collections.Generic.HashSet[string]'
    $add = {
        param([string]$Path)
        if ($Path -and (Test-Path $Path) -and $seen.Add($Path)) {
            $Path
        }
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $exe = & $pyLauncher.Source -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($exe) { & $add ([string]$exe.Trim()) }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { & $add $python.Source }

    $local = $env:LOCALAPPDATA
    if ($local) {
        & $add (Join-Path $local "Programs\Python\Python312\python.exe")
        $coreRoot = Join-Path $local "Python"
        if (Test-Path $coreRoot) {
            Get-ChildItem $coreRoot -Directory -Filter "pythoncore-3.12-*" -ErrorAction SilentlyContinue |
                ForEach-Object { & $add (Join-Path $_.FullName "python.exe") }
        }
    }

    foreach ($key in @("3.12", "3.12-64")) {
        try {
            $installPath = Get-ItemProperty -Path "HKCU:\Software\Python\PythonCore\$key" -Name InstallPath -ErrorAction Stop
            if ($installPath.InstallPath) {
                & $add (Join-Path $installPath.InstallPath "python.exe")
            }
        } catch {}
    }

    return @($seen)
}

function Install-PythonRuntime {
    param(
        [string]$Root,
        $Manifest
    )
    Test-InstallCancelled
    Remove-BrokenVenv -Root $Root
    if (Test-PythonReady -Root $Root) {
        Write-InstallLog "[step 3] Python 3.12 virtual environment is already ready"
        Write-InstallProgress -Phase "python" -Message "Python 3.12 is already installed" -Overall 0.2 -Stage 1
        return
    }

    $systemPy = Get-SystemPython312
    if ($systemPy) {
        Test-InstallCancelled
        Write-InstallProgress -Phase "python" -Message "Creating Python virtual environment…" -Overall 0.15 -Stage 0.5
        $venv = Join-Path $Root ".venv"
        Write-InstallLog "> $systemPy -m venv --copies $venv"
        & $systemPy -m venv --copies $venv
        if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
        Write-InstallLog "  done"
        Write-InstallProgress -Phase "python" -Message "Python environment ready" -Overall 0.25 -Stage 1
        return
    }

    $python = $Manifest.python
    $url = [string]$python.url
    $name = [string]$python.filename
    $expectedMd5 = [string]$python.md5
    $cache = Join-Path $env:TEMP "bob-redist"
    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    $installer = Join-Path $cache $name

    if (-not (Test-Path $installer)) {
        Test-InstallCancelled
        Write-InstallLog "[step 3] Downloading Python 3.12 installer from $url"
        Download-FileWithProgress -Url $url -Destination $installer `
            -Message "Downloading Python 3.12 installer…" -Overall 0.08 -OverallSpan 0.04
        Write-InstallLog "  Python installer downloaded to $installer"
        Test-InstallCancelled
    }
    else {
        Write-InstallLog "[step 3] Using cached Python installer at $installer"
    }
    if ($expectedMd5) {
        $md5 = (Get-FileHash -Algorithm MD5 -Path $installer).Hash.ToLowerInvariant()
        if ($md5 -ne $expectedMd5.ToLowerInvariant()) {
            Remove-Item $installer -Force
            throw "Python installer checksum mismatch"
        }
    }

    $pythonDir = Join-Path $Root "python"
    New-Item -ItemType Directory -Force -Path $pythonDir | Out-Null
    Test-InstallCancelled
    Write-InstallLog "> $installer /quiet TargetDir=$pythonDir ..."
    Write-InstallProgress -Phase "python" -Message "Running Python 3.12 installer…" -Overall 0.12 -Stage 0.6
    $p = Start-Process -FilePath $installer -ArgumentList @(
        "/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_test=0", "Include_doc=0",
        "Include_launcher=0", "InstallLauncherAllUsers=0", "SimpleInstall=1",
        "TargetDir=$pythonDir"
    ) -Wait -PassThru
    $embedPy = Join-Path $pythonDir "python.exe"
    $okCodes = @(0, 3010, 1638)
    if ($okCodes -notcontains $p.ExitCode -and -not (Test-Path $embedPy)) {
        $systemPy = Get-SystemPython312
        if ($systemPy) {
            Write-InstallProgress -Phase "python" -Message "Using existing Python 3.12…" -Overall 0.18 -Stage 0.7
            $venv = Join-Path $Root ".venv"
            & $systemPy -m venv --copies $venv
            if ($LASTEXITCODE -ne 0) { throw "venv creation failed after Python installer exit $($p.ExitCode)" }
            Write-InstallProgress -Phase "python" -Message "Python 3.12 ready" -Overall 0.25 -Stage 1
            return
        }
        throw "Python installer exited $($p.ExitCode)"
    }
    if (-not (Test-Path $embedPy)) {
        throw "Python 3.12 installer finished but python.exe was not found at $embedPy"
    }
    Write-InstallLog "  Python 3.12 installed at $embedPy (exit $($p.ExitCode))"
    $venv = Join-Path $Root ".venv"
    if (-not (Test-VenvReady $Root)) {
        Write-InstallLog "> $embedPy -m venv --copies $venv"
        & $embedPy -m venv --copies $venv
        if ($LASTEXITCODE -ne 0) { throw "venv creation failed after embedded Python install" }
        Write-InstallLog "  done"
    }
    Write-InstallProgress -Phase "python" -Message "Python 3.12 ready" -Overall 0.25 -Stage 1
}

if ($ManifestPath) {
    $manifest = Get-RuntimeManifest -Path $ManifestPath
    if ($InstallFolder) {
        Install-PythonRuntime -Root $InstallFolder -Manifest $manifest
    }
}
