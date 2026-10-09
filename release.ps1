# Release a new version: bumps the app version, builds the signed APK, zips the PC side, tags and publishes on GitHub.
#   .\release.ps1 1.0.1 "מה השתנה, בעברית"
# Needs: the release keystore (outside the repo) + its passwords in ~/.gradle/gradle.properties (see android\app\build.gradle.kts),
# gh logged in, a clean git tree. Without the SAME keystore, phones cannot update over the installed app.
param([Parameter(Mandatory = $true)][string]$Version, [string]$Notes = "")
$ErrorActionPreference = "Stop"
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "version must look like 1.2.3" }
$root = $PSScriptRoot
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { $gh = "$env:ProgramFiles\GitHub CLI\gh.exe" }
if (git -C $root status --porcelain) { throw "commit your changes first" }

# 1. version in the app (versionCode = major*10000 + minor*100 + patch)
$p = $Version.Split(".") | ForEach-Object { [int]$_ }
$code = $p[0] * 10000 + $p[1] * 100 + $p[2]
$gradle = "$root\android\app\build.gradle.kts"
$t = [IO.File]::ReadAllText($gradle)
$t = $t -replace 'versionCode = \d+', "versionCode = $code" -replace 'versionName = "[^"]*"', "versionName = `"$Version`""
[IO.File]::WriteAllText($gradle, $t, (New-Object Text.UTF8Encoding $false))

# 2. signed APK
Push-Location "$root\android"
try { & .\gradlew.bat assembleRelease --no-daemon -q; if ($LASTEXITCODE) { throw "gradle failed" } } finally { Pop-Location }
$apkSrc = "$root\android\app\build\outputs\apk\release\app-release.apk"
if (-not (Test-Path $apkSrc)) { throw "no signed APK: is the keystore set in ~/.gradle/gradle.properties?" }

# 3. assets
$dist = "$root\dist"
Remove-Item $dist -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $dist | Out-Null
$apk = "$dist\shema-v$Version.apk"
Copy-Item $apkSrc $apk
$stage = "$dist\shema"
New-Item -ItemType Directory $stage | Out-Null
Copy-Item "$root\server", "$root\install" $stage -Recurse
Copy-Item "$root\requirements.txt", "$root\README.md", "$root\LICENSE" $stage
Get-ChildItem $stage -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
$zip = "$dist\shema-windows-v$Version.zip"
Compress-Archive -Path $stage -DestinationPath $zip

# 4. commit the version, tag, publish
git -C $root commit -am "Release v$Version"
git -C $root tag "v$Version"
git -C $root push --follow-tags
if (-not $Notes) { $Notes = "גרסה $Version" }
& $gh release create "v$Version" $apk $zip --title "שמע v$Version" --notes $Notes
Write-Host "Published: https://github.com/$((& $gh repo view --json nameWithOwner -q .nameWithOwner))/releases/tag/v$Version"
