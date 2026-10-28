# Build a signed release Android App Bundle (.aab) for Google Play Console upload.
param(
    [string]$VersionName = "1.0.0",
    [int]$VersionCode = 1,
    # -Upload: send the bundle to Google Play right after the build (play_upload.py, service-account key)
    [switch]$Upload,
    [ValidateSet("draft", "completed", "inProgress")]
    [string]$Status = "draft",
    [double]$Fraction = 0.2,
    [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$androidDir = Join-Path $root "android"
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Building Shema Pro (.aab) for Google Play   " -ForegroundColor Cyan
Write-Host " Version: $VersionName (Code: $VersionCode) " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# 1. Check keystore
$gradleProps = "$env:USERPROFILE\.gradle\gradle.properties"
if (-not (Test-Path $gradleProps)) {
    throw "Missing ~/.gradle/gradle.properties with SHEMA_STORE_FILE"
}

# 2. Run Gradle bundleRelease
Push-Location $androidDir
try {
    Write-Host "Running gradlew bundleRelease..." -ForegroundColor Yellow
    & .\gradlew.bat bundleRelease --no-daemon
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle bundleRelease failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

# 3. Locate output AAB
$aabSrc = "$androidDir\app\build\outputs\bundle\release\app-release.aab"
if (-not (Test-Path $aabSrc)) {
    throw "Output AAB not found at $aabSrc"
}

# 4. Copy to dist
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Path $dist -Force | Out-Null
$targetAab = Join-Path $dist "shema-pro-v$VersionName.aab"
Copy-Item $aabSrc $targetAab -Force

$sizeMb = [math]::Round((Get-Item $targetAab).Length / 1MB, 2)
Write-Host ""
Write-Host "SUCCESS! Bundle created successfully:" -ForegroundColor Green
Write-Host "File: $targetAab" -ForegroundColor Green
Write-Host "Size: $sizeMb MB" -ForegroundColor Green
Write-Host "Ready to be uploaded to Google Play Console (https://play.google.com/console)!" -ForegroundColor Cyan

# 5. Upload to Google Play (optional)
if ($Upload) {
    Write-Host ""
    Write-Host "Uploading to Google Play ($Status)..." -ForegroundColor Yellow
    & python (Join-Path $PSScriptRoot "play_upload.py") $targetAab --status $Status --fraction $Fraction --notes $Notes
    if ($LASTEXITCODE -ne 0) {
        throw "Upload to Google Play failed (the .aab is still in dist)"
    }
}
