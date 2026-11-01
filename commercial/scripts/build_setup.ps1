# Builds the one-file Windows installer:  .\build_setup.ps1 1.0.15   ->  commercial\dist\ShemaSetup.exe
# Same files as the release zip (git ls-files of server, install, requirements.txt, LICENSE), staged to a clean folder so
# untracked or cached files never ship. The name stays ShemaSetup.exe so .../releases/latest/download/ShemaSetup.exe
# always gets the newest one. Needs Inno Setup 6:  winget install --id JRSoftware.InnoSetup -e --scope user
param([Parameter(Mandatory = $true)][string]$Version, [string]$Out = "")
$ErrorActionPreference = "Stop"
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "version must look like 1.2.3" }
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $Out) { $Out = Join-Path $root "commercial\dist" }
$have = (Get-Content (Join-Path $root "server\VERSION") -Raw).Trim()
if ($have -ne $Version) { throw "server/VERSION is '$have', not '$Version': the update button compares it with the release tag" }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found: winget install --id JRSoftware.InnoSetup -e --scope user" }

$stage = Join-Path ([IO.Path]::GetTempPath()) "shema-setup-$Version"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
$files = git -C $root ls-files server install requirements.txt LICENSE
foreach ($f in $files) {
    $dst = Join-Path $stage $f
    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
    Copy-Item (Join-Path $root $f) $dst
}
New-Item -ItemType Directory -Force $Out | Out-Null
& $iscc /Q "/DAppVersion=$Version" "/DSrc=$stage" "/O$Out" (Join-Path $PSScriptRoot "ShemaSetup.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed ($LASTEXITCODE)" }
Remove-Item $stage -Recurse -Force
$exe = Get-Item (Join-Path $Out "ShemaSetup.exe")
Write-Host "Created: $($exe.FullName) ($([math]::Round($exe.Length / 1KB)) KB, $($files.Count) files)"
