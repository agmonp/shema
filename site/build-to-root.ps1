# Builds the 3D landing page and copies it to the repo root, where GitHub Pages
# serves https://shema.agmonp.com/ from (branch main, folder /).
# Usage: .\site\build-to-root.ps1     then commit index.html + assets\ and push main.
$ErrorActionPreference = 'Stop'
$site = $PSScriptRoot
$root = Split-Path $site -Parent

Push-Location $site
try {
    if (-not (Test-Path node_modules)) { npm install --no-fund --no-audit }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'build failed' }
} finally { Pop-Location }

# keep the previous long page (FAQ, install notes) as classic.html, once
$classic = Join-Path $root 'classic.html'
if (-not (Test-Path $classic)) {
    $old = Get-Content (Join-Path $root 'index.html') -Raw -Encoding utf8
    if ($old -notmatch 'id="root"') { Set-Content $classic $old -Encoding utf8 -NoNewline }
}

$assets = Join-Path $root 'assets'
if (Test-Path $assets) { Remove-Item $assets -Recurse -Force }
Copy-Item (Join-Path $site 'dist\assets') $assets -Recurse
Copy-Item (Join-Path $site 'dist\index.html') (Join-Path $root 'index.html') -Force
Write-Host "Copied to $root (index.html + assets\). Old page: classic.html"
