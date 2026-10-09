# For developers: install "Shema" on an Android phone connected by USB and pair it with this PC (adb).
# Normal users do not need this: download the APK from /home/app.apk and scan the QR in the app.
#   .\install_phone.ps1                 -> the personal phone that goes out (default)
#   .\install_phone.ps1 -Role home      -> a phone that STAYS at home (records only at home)
#   .\install_phone.ps1 -Apk path\to\shema.apk
# Needs on the phone, once: Settings > About phone > tap "Build number" 7 times, then Developer options >
# USB debugging = on, and approve "Allow USB debugging". Xiaomi (HyperOS, MIUI): also "Install via USB".
# OPPO / realme / OnePlus (ColorOS): "Install via USB" if present, or "Disable permission monitoring".
param([ValidateSet("home", "wearer")][string]$Role = "wearer", [string]$Apk = "", [int]$Port = 8770)
$ErrorActionPreference = "Continue"
$pkg = "app.shema.listener"
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
if (-not (Test-Path $adb)) { $adb = "adb" }
if (-not $Apk) {
    $Apk = @("$PSScriptRoot\app\build\outputs\apk\release\app-release.apk", "$PSScriptRoot\app\build\outputs\apk\debug\app-debug.apk",
             "$env:LOCALAPPDATA\Shema\app.apk") | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Apk) { Write-Host "No APK found. Build it (gradlew assembleRelease) or pass -Apk."; exit 1 }
$cfgPath = "$env:LOCALAPPDATA\Shema\data\config.json"
if (-not (Test-Path $cfgPath)) { Write-Host "No $cfgPath : run install\Install.bat on this PC first."; exit 1 }
$cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -in 'Dhcp','Manual' -and $_.IPAddress -notlike '169.*' -and $_.IPAddress -notlike '100.*' } | Select-Object -First 1).IPAddress
$server = "http://${ip}:$Port"

$dev = & $adb devices | Select-String "`tdevice$"
if (-not $dev) { Write-Host "No phone found. Connect by USB and allow USB debugging on the phone."; exit 1 }
$out = (& $adb install -r $Apk 2>&1 | Out-String)
if ($out -notmatch "Success") {
    Write-Host "INSTALL FAILED: $out"
    if ($out -match "USER_RESTRICTED") { Write-Host "Xiaomi: Developer options > 'Install via USB'. OPPO/realme: 'Disable permission monitoring' / 'Install via USB'." }
    exit 2
}
$extra = @()
if ($cfg.remote) { $extra = @("--es", "remote", "http://$($cfg.remote):$Port") }
& $adb shell am start -n "$pkg/.MainActivity" --es server $server --es token $cfg.token --es role $Role @extra | Out-Null
Write-Host "Installed ($Role) and paired with $server. On the phone: accept the permissions the app asks for, then 'Teach my voice'."
