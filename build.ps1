Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (Test-Path build) {
    Remove-Item -Recurse -Force build
}

if (Test-Path dist) {
    Remove-Item -Recurse -Force dist
}

pyinstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name NameCutter `
    --paths src `
    main.py

Write-Host "Build complete: dist\\NameCutter.exe"

