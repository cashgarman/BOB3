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
$env:OLLAMA_GPU_OVERHEAD = "1610612736"

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
if (Test-Path $bob) { $pythonw = $bob }
elseif (-not (Test-Path $pythonw)) { $pythonw = $python }
Write-Host "Bob is in the system tray. Right-click the icon for settings. Quit from the tray."
Start-Process -FilePath $pythonw -ArgumentList "-m","bob" -WorkingDirectory $PSScriptRoot
