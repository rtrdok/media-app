# Zip portable build for GitHub Releases
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dist = Join-Path $root "dist\MediaApp"
$out = Join-Path $root "dist\MediaApp.zip"
if (-not (Test-Path (Join-Path $dist "MediaApp.exe"))) {
  throw "Build exe first: scripts\build-exe.ps1"
}
if (Test-Path $out) { Remove-Item $out -Force }
# Не кладём пользовательские данные в релизный zip
$exclude = @(".env", "cookies.txt", "history.db", "media_app.log", "config", "file_cache")
$staging = Join-Path $root "dist\MediaApp_release_staging"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging | Out-Null
Copy-Item -Path (Join-Path $dist "*") -Destination $staging -Recurse -Force
foreach ($name in $exclude) {
  $p = Join-Path $staging $name
  if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
}
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $out -Force
Remove-Item $staging -Recurse -Force
Write-Host "Done: $out"
