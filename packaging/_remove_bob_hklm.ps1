# One-shot HKLM BOB uninstall registry cleanup (requires admin)
& (Join-Path (Split-Path $PSScriptRoot -Parent) "cleanup-bob-installs.ps1") -RegistryOnly -Force
