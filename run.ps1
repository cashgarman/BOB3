$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "No .venv found. Run .\setup.ps1 first."
    exit 1
}

# Session-only Ollama hints for a *new* ollama process. The already-running
# daemon keeps its original env; the app still passes num_ctx / keep_alive.
$env:OLLAMA_MAX_LOADED_MODELS = "1"
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_FLASH_ATTENTION = "1"
$overhead = "1610612736"
$cfg = Join-Path $PSScriptRoot "config.yaml"
if (Test-Path $cfg) {
    $match = Select-String -Path $cfg -Pattern '^\s*ollama_gpu_overhead:\s*(\d+)' | Select-Object -First 1
    if ($match) { $overhead = $match.Matches[0].Groups[1].Value }
}
$env:OLLAMA_GPU_OVERHEAD = $overhead

$nvidia = Join-Path $PSScriptRoot ".venv\Lib\site-packages\nvidia"
if (Test-Path $nvidia) {
    Get-ChildItem $nvidia -Directory | ForEach-Object {
        $bin = Join-Path $_.FullName "bin"
        if (Test-Path $bin) { $env:PATH = "$bin;$env:PATH" }
    }
}

if ($args -contains "--check") {
    & $python -m bob @args
    exit $LASTEXITCODE
}

. (Join-Path $PSScriptRoot "stop_bob.ps1")
Stop-BobInstances -ProjectRoot $PSScriptRoot | Out-Null

$bob = Join-Path $PSScriptRoot ".venv\Scripts\Bob.exe"
$pythonw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
$target = $bob
$launchArgs = @()
$useSource = -not (Test-Path $target)
if (-not $useSource) {
    $srcMarker = Join-Path $PSScriptRoot "bob\llm.py"
    if ((Test-Path $srcMarker) -and (Get-Item $srcMarker).LastWriteTime -gt (Get-Item $target).LastWriteTime) {
        $useSource = $true
    }
}
if ($useSource) {
    $target = $(if (Test-Path $pythonw) { $pythonw } else { $python })
    $launchArgs = @("-m", "bob")
}
Write-Host "BOB is in the system tray. Right-click the icon for settings. Quit from the tray."
if ($launchArgs.Count -gt 0) {
    Start-Process -FilePath $target -ArgumentList $launchArgs -WorkingDirectory $PSScriptRoot
} else {
    Start-Process -FilePath $target -WorkingDirectory $PSScriptRoot
}
