$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location (Join-Path $root "web-ui")
npm run build
Write-Host "UI -> web/static (run PyInstaller to refresh dist)"
