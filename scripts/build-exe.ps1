$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  throw "Use project venv (Python 3.11): python -m venv .venv && .venv\Scripts\pip install -r requirements.txt pyinstaller"
}
& $py -m pip install -r (Join-Path $root "requirements.txt") pyinstaller -q
Set-Location (Join-Path $root "web-ui")
& npm run build
Set-Location $root
& $py -m PyInstaller MediaApp.spec --clean -y
Write-Host "Done: dist\MediaApp\MediaApp.exe"
