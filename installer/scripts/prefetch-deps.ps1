$ErrorActionPreference = "Stop"
$InstallerRoot = Split-Path -Parent $PSScriptRoot
$DepDir = Join-Path $InstallerRoot "deps"
New-Item -ItemType Directory -Force -Path $DepDir | Out-Null

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

function Invoke-Download([string]$Url, [string]$OutFile, [string]$ExpectedSha) {
    if (Test-Path $OutFile) {
        if ($ExpectedSha) {
            $actual = Get-Sha256 $OutFile
            if ($actual -eq $ExpectedSha.ToLowerInvariant()) {
                Write-Host "Using cached $(Split-Path $OutFile -Leaf)"
                return
            }
            Write-Host "Checksum mismatch for $(Split-Path $OutFile -Leaf); re-downloading"
            Remove-Item $OutFile -Force
        } else {
            Write-Host "Using cached $(Split-Path $OutFile -Leaf)"
            return
        }
    }
    Write-Host "Downloading $Url"
    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
    if ($ExpectedSha) {
        $actual = Get-Sha256 $OutFile
        if ($actual -ne $ExpectedSha.ToLowerInvariant()) {
            throw "SHA256 mismatch for $OutFile expected $ExpectedSha got $actual"
        }
    }
}

# Optional: prefetch Python for offline MSI builds on the build machine only.
# Ollama is never bundled — InstallOllama.exe downloads it on the end-user PC.
$manifest = Get-Content (Join-Path $InstallerRoot "runtime-deps.json") -Raw | ConvertFrom-Json
$pythonName = [string]$manifest.python.filename
$pythonUrl = [string]$manifest.python.url
$pythonMd5 = [string]$manifest.python.md5

$pythonOut = Join-Path $DepDir $pythonName
if (-not (Test-Path $pythonOut)) {
    Invoke-Download $pythonUrl $pythonOut $null
}
$md5 = (Get-FileHash -Algorithm MD5 -Path $pythonOut).Hash.ToLowerInvariant()
if ($md5 -ne $pythonMd5.ToLowerInvariant()) {
    throw "Python installer MD5 mismatch expected $pythonMd5 got $md5"
}

$sumFile = Join-Path $DepDir "SHA256SUMS"
"$(Get-Sha256 $pythonOut)  $pythonName" | Set-Content -Path $sumFile -Encoding ascii
Write-Host "Optional build cache ready in $DepDir (Python only)."
Write-Host "Ollama is downloaded on the target PC during BobSetup.exe."
