$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$dist = Join-Path $root "commercial\dist"
$stage = Join-Path $dist "shema-windows"

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

Copy-Item -Path (Join-Path $root "server"), (Join-Path $root "install") -Destination $stage -Recurse
Copy-Item -Path (Join-Path $root "requirements.txt"), (Join-Path $root "README.md"), (Join-Path $root "LICENSE") -Destination $stage

Get-ChildItem $stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $stage -Recurse -Directory -Filter ".pytest_cache" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$zipPath = Join-Path $dist "shema-windows-v1.0.2.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

Compress-Archive -Path "$stage\*" -DestinationPath $zipPath
Remove-Item $stage -Recurse -Force

Write-Host "Created: $zipPath ($( (Get-Item $zipPath).Length ) bytes)"
