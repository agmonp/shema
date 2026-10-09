# Shema (שמע) -- installer for the PC side. Run Install.bat (double click). Safe to run again: it updates, it does not break.
#
#   What it does: checks the PC, picks the speech / summary models for this hardware, installs Python 3.11, ffmpeg and
#   Ollama (winget), a private Python environment, the models, the access code and config.json, a firewall rule for the
#   home network, a logon task that runs the server in the background, a "שמע" shortcut, and the phone app (APK).
#   It never turns off Smart App Control or any other protection.
#
#   Everything goes to %LOCALAPPDATA%\Shema   (app, venv, models, data, app.apk)
#
#   Options (for testing / advanced):  -Port 8770  -ShemaHome DIR  -Owner NAME  -Quiet  -Test  -SkipOllama  -SkipModels  -Apk FILE
#   -Test: nothing outside ShemaHome is touched (no task, no firewall rule, no shortcuts, no winget installs).
param(
    [int]$Port = 8770,
    [string]$ShemaHome = "",
    [string]$Owner = "",
    [switch]$Quiet,
    [switch]$Test,
    [switch]$SkipOllama,
    [switch]$SkipModels,
    [string]$Apk = "",
    [string]$Python = "",
    [string]$Repo = "agmonp/shema"
)
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

if (-not $ShemaHome) { $ShemaHome = Join-Path $env:LOCALAPPDATA "Shema" }
$Src = Split-Path -Parent $PSScriptRoot                    # the unpacked folder (server\, install\, requirements.txt)
$App = Join-Path $ShemaHome "app"
$Venv = Join-Path $ShemaHome "venv"
$Models = Join-Path $ShemaHome "models"
$Data = Join-Path $ShemaHome "data"
$ApkDst = Join-Path $ShemaHome "app.apk"
New-Item -ItemType Directory -Force $ShemaHome, $Models, $Data | Out-Null
$env:SHEMA_HOME = $ShemaHome
try { Start-Transcript -Path (Join-Path $ShemaHome "install.log") -Append | Out-Null } catch { }

# ------------------------------------------------------------------ dialogs (Hebrew reads right in a Windows dialog, not in the console)
$script:forms = $false
try { Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName Microsoft.VisualBasic; $script:forms = $true } catch { }
$RTL = 0x180000   # MessageBoxOptions.RtlReading | RightAlign

function Say([string]$text, [string]$kind = "Information") {
    Write-Host ""
    Write-Host $text
    if ($Quiet -or -not $script:forms) { return }
    try { [System.Windows.Forms.MessageBox]::Show($text, "שמע", "OK", $kind, "Button1", $RTL) | Out-Null } catch { }
}
function Ask([string]$text, [bool]$default = $true) {
    Write-Host ""
    Write-Host $text
    if ($Quiet) { return $default }
    if ($script:forms) {
        try { return ([System.Windows.Forms.MessageBox]::Show($text, "שמע", "YesNo", "Question", "Button1", $RTL) -eq "Yes") } catch { }
    }
    return ((Read-Host "y/n") -match '^(y|yes|כ|כן)')
}
function AskText([string]$text, [string]$default) {
    if ($Quiet) { return $default }
    if ($script:forms) {
        try { return [Microsoft.VisualBasic.Interaction]::InputBox($text, "שמע", $default) } catch { }
    }
    $r = Read-Host $text
    if ($r) { return $r } else { return $default }
}
function Step([string]$t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Fail([string]$text) {
    Say $text "Error"
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

# ------------------------------------------------------------------ 1. checks
Step "1/11 Checking this PC"
if (-not [Environment]::Is64BitOperatingSystem) { Fail "שמע צריך Windows של 64 ביט." }
$build = [Environment]::OSVersion.Version.Build
if ([Environment]::OSVersion.Version.Major -lt 10 -or $build -lt 17763) { Fail "שמע צריך Windows 10 (גרסה 1809 ומעלה) או Windows 11." }
$drive = (Get-Item $ShemaHome).PSDrive
$freeGb = [math]::Round(((Get-PSDrive $drive.Name).Free) / 1GB, 1)
Write-Host "Windows build $build, free space on $($drive.Name): $freeGb GB"
if ($freeGb -lt 15) { Fail "אין מספיק מקום פנוי בכונן $($drive.Name): (יש $freeGb GB, צריך לפחות 15 GB)." }
$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget -and -not $Test) {
    Fail "חסר winget (מנהל ההתקנות של Windows). התקן את App Installer מ-Microsoft Store והרץ שוב את Install.bat."
}

# ------------------------------------------------------------------ 2. graphics card -> models
Step "2/11 Graphics card"
$gpuName = $null; $vram = 0
$smi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source
if (-not $smi -and (Test-Path "$env:WINDIR\System32\nvidia-smi.exe")) { $smi = "$env:WINDIR\System32\nvidia-smi.exe" }
if ($smi) {
    $line = (& $smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
    if ($line -match '^(.+?),\s*(\d+)') { $gpuName = $Matches[1].Trim(); $vram = [int]$Matches[2] }
}
if ($gpuName -and $vram -ge 8000) { $device = "cuda"; $compute = "float16" } else { $device = "cpu"; $compute = "int8" }
if ($vram -ge 12000) { $summary = "gemma3:12b" } else { $summary = "gemma3:4b" }
$whisper = "ivrit-ai/whisper-large-v3-turbo-ct2"   # ivrit.ai has no smaller Hebrew ct2 model; on CPU it runs int8
if ($gpuName) { Write-Host "NVIDIA: $gpuName, $vram MB" } else { Write-Host "No NVIDIA card found" }
Write-Host "Speech: $whisper on $device ($compute).  Summaries: $summary (Ollama)"
if ($device -eq "cpu") {
    $why = if ($gpuName) { "כרטיס המסך ($gpuName) קטן מ-8GB" } else { "לא נמצא כרטיס מסך של NVIDIA" }
    Say ("$why, לכן התמלול ירוץ על המעבד (CPU).`n`nזה עובד, אבל לאט יותר: ההקלטות מצטברות ומתומללות לאורך היום, ולא מיד. " +
         "הסיכומים ישתמשו במודל הקטן ($summary).")
}

# ------------------------------------------------------------------ 3. Smart App Control (we only look; we never change it)
Step "3/11 Smart App Control"
$sac = $null
try { $sac = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy" -Name VerifiedAndReputablePolicyState -ErrorAction Stop).VerifiedAndReputablePolicyState } catch { }
$sacOn = ($sac -eq 1)
Write-Host ("Smart App Control: " + $(switch ($sac) { 0 { "off" } 1 { "ON" } 2 { "evaluation" } default { "not present" } }))
if ($sacOn) {
    $msg = "במחשב הזה פועל Smart App Control (בקרת אפליקציות חכמה) של Windows.`n`n" +
        "זו הגנה שחוסמת קבצים בלי חתימה מוכרת. היא עלולה לחסום חלק מספריות ה-Python ששמע צריך. " +
        "במקרה כזה מופיעה ההודעה: An Application Control policy has blocked this file.`n`n" +
        "ההתקנה לא תכבה אותה ולא תשנה שום הגנה.`n`n" +
        "האפשרויות שלך:`n" +
        "1. להמשיך. בסוף ההתקנה נבדוק אם משהו נחסם ונגיד לך בדיוק מה.`n" +
        "2. להתקין את צד המחשב של שמע על מחשב אחר בבית.`n" +
        "3. לכבות את Smart App Control בעצמך (אבטחת Windows ← בקרת אפליקציות ודפדפן). שים לב: אי אפשר להפעיל אותו שוב בלי להתקין את Windows מחדש. ההחלטה שלך בלבד.`n`n" +
        "להמשיך בהתקנה עכשיו?"
    if (-not (Ask $msg $true)) { Fail "ההתקנה נעצרה. לא שונה כלום במחשב." }
}

# ------------------------------------------------------------------ 4. Python 3.11, ffmpeg, Ollama
function WingetInstall([string]$id, [string]$what) {
    if ($Test) { Write-Host "(test) skip winget $id"; return }
    Write-Host "Installing $what ..."
    & winget install --id $id -e --silent --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) {   # some packages have no per-user installer
        & winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    }
}
function FindPython {
    if ($Python -and (Test-Path $Python)) { return $Python }
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python311\python.exe", "$env:ProgramFiles\Python311\python.exe")) {
        if (Test-Path $p) { return $p }
    }
    try { $p = (& py -3.11 -c "import sys; print(sys.executable)" 2>$null); if ($p -and (Test-Path $p)) { return $p } } catch { }
    return $null
}
function FindFfmpeg {
    $c = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
    if ($c) { return $c }
    $f = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match 'Gyan\.FFmpeg' } | Sort-Object FullName | Select-Object -Last 1
    if ($f) { return $f.FullName }
    return $null
}

Step "4/11 Python 3.11 and ffmpeg"
$py = FindPython
if (-not $py) { WingetInstall "Python.Python.3.11" "Python 3.11"; $py = FindPython }
if (-not $py) { Fail "לא הצלחתי להתקין את Python 3.11. התקן אותו מ-python.org (גרסה 3.11, 64 ביט) והרץ שוב." }
Write-Host "Python: $py"
$ff = FindFfmpeg
if (-not $ff) { WingetInstall "Gyan.FFmpeg" "ffmpeg"; $ff = FindFfmpeg }
if (-not $ff) { Fail "לא הצלחתי להתקין את ffmpeg. הרץ: winget install Gyan.FFmpeg ואז שוב את Install.bat." }
$opus = (& $ff -hide_banner -encoders 2>$null | Select-String libopus)
Write-Host "ffmpeg: $ff  (libopus: $([bool]$opus))"
if (-not $opus) { Say "ל-ffmpeg שנמצא אין libopus. שמע יעבוד, אבל הארכיון יישמר בפורמט גדול יותר. מומלץ: winget install Gyan.FFmpeg" "Warning" }

# ------------------------------------------------------------------ 5. stop a running server (an update replaces its files)
Step "5/11 Stopping a running Shema server (if any)"
if (-not $Test) { try { Stop-ScheduledTask -TaskName "Shema" -ErrorAction Stop } catch { } }
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$App\home_listener.py*" } |
    ForEach-Object { Write-Host "stopping pid $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# ------------------------------------------------------------------ 6. code + Python environment
Step "6/11 Program files and Python packages (several GB the first time)"
& robocopy "$Src\server" $App /MIR /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
foreach ($f in "uninstall.ps1", "Uninstall.bat") { Copy-Item (Join-Path $PSScriptRoot $f) (Join-Path $ShemaHome $f) -Force }
if (-not (Test-Path "$Venv\Scripts\python.exe")) { & $py -m venv $Venv }
$vpy = "$Venv\Scripts\python.exe"
$vpyw = "$Venv\Scripts\pythonw.exe"
if (-not (Test-Path $vpy)) { Fail "יצירת סביבת ה-Python נכשלה ($Venv)." }
& $vpy -m pip install --upgrade pip --disable-pip-version-check -q
$torchWant = if ($device -eq "cuda") { "cu128" } else { "cpu" }
$torchHave = "$(& $vpy -c "import torch; print(torch.__version__)" 2>$null)".Trim()
if ($torchHave -notlike "2.11.0+$torchWant") {
    Write-Host "Installing torch ($torchWant) ..."
    & $vpy -m pip install --disable-pip-version-check "torch==2.11.0+$torchWant" "torchaudio==2.11.0+$torchWant" --index-url "https://download.pytorch.org/whl/$torchWant"
    if ($LASTEXITCODE -ne 0) { Fail "התקנת torch נכשלה. בדוק את החיבור לאינטרנט והרץ שוב (פרטים ב-$ShemaHome\install.log)." }
}
& $vpy -m pip install --disable-pip-version-check -r "$Src\requirements.txt"
if ($LASTEXITCODE -ne 0) { Fail "התקנת ספריות ה-Python נכשלה. הרץ שוב את Install.bat (פרטים ב-$ShemaHome\install.log)." }

# ------------------------------------------------------------------ 7. models
Step "7/11 Models"
function Fetch([string]$url, [string]$dst) {
    if ((Test-Path $dst) -and (Get-Item $dst).Length -gt 1000) { return }
    Write-Host "downloading $(Split-Path $dst -Leaf) ..."
    & curl.exe -L --fail --retry 3 -s -S -o "$dst.part" $url
    if ($LASTEXITCODE -ne 0) { Fail "הורדת מודל נכשלה: $url" }
    Move-Item "$dst.part" $dst -Force
}
$K2 = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
Fetch "$K2/asr-models/silero_vad.onnx" "$Models\silero_vad.onnx"
Fetch "$K2/speaker-recongition-models/3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx" "$Models\3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx"
Fetch "$K2/speaker-recongition-models/nemo_en_titanet_large.onnx" "$Models\nemo_en_titanet_large.onnx"
$ced = "$Models\sherpa-onnx-ced-base-audio-tagging-2024-04-19"
if (-not (Test-Path "$ced\model.int8.onnx")) {
    Fetch "$K2/audio-tagging-models/sherpa-onnx-ced-base-audio-tagging-2024-04-19.tar.bz2" "$Models\ced.tar.bz2"
    & tar -xjf "$Models\ced.tar.bz2" -C $Models
    if (-not (Test-Path "$ced\model.int8.onnx")) { Fail "פתיחת מודל הצלילים נכשלה." }
    Remove-Item "$Models\ced.tar.bz2", "$ced\model.onnx" -ErrorAction SilentlyContinue      # only the int8 model is used
    Remove-Item "$ced\test_wavs" -Recurse -ErrorAction SilentlyContinue
}

# ------------------------------------------------------------------ 8. config.json (access code, owner, hardware choices)
Step "8/11 Settings"
$ts = $null
$tsExe = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $tsExe -and (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe")) { $tsExe = "$env:ProgramFiles\Tailscale\tailscale.exe" }
if ($tsExe) { $ts = "$(& $tsExe ip -4 2>$null | Select-Object -First 1)".Trim(); if ($ts -notmatch '^100\.\d+\.\d+\.\d+$') { $ts = $null } }
$cfgPath = Join-Path $Data "config.json"
$haveOwner = $false
if (Test-Path $cfgPath) { try { $haveOwner = [bool]((Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json).owner_name) } catch { } }
if (-not $haveOwner -and -not $Owner) {
    $Owner = AskText "איך קוראים לך? הקול הראשי (שלך) ייקרא בשם הזה במסכים ובסיכומים." ""
}
$cfgArgs = @("--device", $device, "--compute", $compute, "--summary", $summary)
if ($Owner) { $cfgArgs += @("--owner", $Owner) }
if ($ts) { $cfgArgs += @("--remote", $ts) }
& $vpy -X utf8 "$App\setup_config.py" @cfgArgs
if ($LASTEXITCODE -ne 0) { Fail "כתיבת ההגדרות נכשלה." }

# ------------------------------------------------------------------ 9. import check (Smart App Control shows up here) + model download
Step "9/11 Checking that Windows lets the Python libraries load"
$stArgs = @("-X", "utf8", "$App\selftest.py")
if (-not $SkipModels) { $stArgs += "--prefetch"; Write-Host "(also downloading the speech and emotion models, a few GB the first time)" }
$st = (& $vpy @stArgs 2>&1 | Out-String)
$stJson = $null
if ($st -match 'SELFTEST (\{.*\})') { try { $stJson = $Matches[1] | ConvertFrom-Json } catch { } }
if (-not $stJson -or $stJson.fatal) { Write-Host $st; Fail "בדיקת הספריות נכשלה. הפרטים ב-$ShemaHome\install.log" }
$errs = @($stJson.errors.PSObject.Properties)
if ($errs.Count -gt 0) {
    $list = ($errs | ForEach-Object { "• $($_.Name): $($_.Value)" }) -join "`n"
    if ($stJson.blocked_by_policy) {
        Fail ("Windows חסם ספריות ש'שמע' צריך:`n$list`n`n" +
              "זו החסימה של Smart App Control. ההתקנה לא מכבה אותה. האפשרויות: להתקין את צד המחשב על מחשב אחר, " +
              "או לכבות בעצמך את Smart App Control (בלתי הפיך בלי התקנה מחדש של Windows) ולהריץ שוב את Install.bat.")
    }
    Fail "ספריות לא נטענו:`n$list`n`nהרץ שוב את Install.bat. אם זה חוזר, הפרטים ב-$ShemaHome\install.log"
}
Write-Host "torch / faster_whisper / sherpa_onnx: OK  (CUDA: $($stJson.cuda))"
if ($device -eq "cuda" -and -not $stJson.cuda) {
    & $vpy -X utf8 "$App\setup_config.py" --device cpu --compute int8 --summary $summary | Out-Null
    $device = "cpu"
    Say "כרטיס ה-NVIDIA לא זמין ל-Python (בדרך כלל דרייבר ישן). שמע יעבוד על המעבד בינתיים. אחרי עדכון דרייבר של NVIDIA הרץ שוב את Install.bat." "Warning"
}

# ------------------------------------------------------------------ 10. Ollama (summaries) + the phone app
Step "10/11 Ollama and the phone app"
if (-not $SkipOllama) {
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollama -and (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")) { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
    if (-not $ollama) {
        WingetInstall "Ollama.Ollama" "Ollama"
        if (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe") { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
    }
    if ($ollama) {
        $up = $false
        for ($i = 0; $i -lt 30 -and -not $up; $i++) {
            try { Invoke-RestMethod "http://127.0.0.1:11434/api/version" -TimeoutSec 2 | Out-Null; $up = $true }
            catch { if ($i -eq 2) { Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden }; Start-Sleep 2 }
        }
        Write-Host "ollama pull $summary ..."
        & $ollama pull $summary
        if ($LASTEXITCODE -ne 0) { Say "הורדת מודל הסיכומים ($summary) נכשלה. השיחות יתומללו, והסיכומים יופיעו אחרי שתריץ שוב את Install.bat." "Warning" }
    } else {
        Say "Ollama לא הותקן, לכן לא יהיו סיכומי שיחות. אפשר להתקין מ-ollama.com ולהריץ שוב." "Warning"
    }
}
if ($Apk -and (Test-Path $Apk)) {
    Copy-Item $Apk $ApkDst -Force
} elseif (-not $Test) {
    try {
        $rel = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "shema-installer" } -TimeoutSec 30
        $asset = $rel.assets | Where-Object { $_.name -like "*.apk" } | Select-Object -First 1
        if ($asset) {
            & curl.exe -L --fail --retry 3 -s -S -o "$ApkDst.part" $asset.browser_download_url
            if ($LASTEXITCODE -eq 0) { Move-Item "$ApkDst.part" $ApkDst -Force; Write-Host "phone app: $($asset.name)" }
        }
    } catch { Write-Host "could not reach GitHub Releases: $_" }
    if (-not (Test-Path $ApkDst)) {
        $local = Get-ChildItem $Src -Filter "*.apk" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($local) { Copy-Item $local.FullName $ApkDst -Force }
        else { Say "לא הצלחתי להוריד את אפליקציית הטלפון. אפשר להוריד אותה ישירות מ-https://github.com/$Repo/releases/latest" "Warning" }
    }
}

# ------------------------------------------------------------------ 11. firewall, background task, shortcuts
Step "11/11 Network, background start and shortcuts"
if ($Test) {
    Write-Host "(test) no firewall rule, task or shortcut. Start the server with:"
    Write-Host "  `$env:SHEMA_HOME='$ShemaHome'; `$env:HOME_PORT=$Port; & '$vpy' -X utf8 '$App\home_listener.py'"
} else {
    $basePy = "$(& $vpy -c "import sys; print(sys._base_executable)" 2>$null)".Trim()
    $basePyw = Join-Path (Split-Path $basePy) "pythonw.exe"
    $fw = @"
Remove-NetFirewallRule -Group 'Shema' -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName 'Shema (home network)' -Group 'Shema' -Direction Inbound -Protocol TCP -LocalPort $Port -Profile Private -Action Allow | Out-Null
New-NetFirewallRule -DisplayName 'Shema server (home network)' -Group 'Shema' -Direction Inbound -Program '$basePyw' -Protocol TCP -LocalPort $Port -Profile Private -Action Allow | Out-Null
"@
    if ($ts) {
        $fw += "`nNew-NetFirewallRule -DisplayName 'Shema (Tailscale)' -Group 'Shema' -Direction Inbound -Protocol TCP -LocalPort $Port -RemoteAddress 100.64.0.0/10 -Action Allow | Out-Null"
        $fw += "`nNew-NetFirewallRule -DisplayName 'Shema server (Tailscale)' -Group 'Shema' -Direction Inbound -Program '$basePyw' -Protocol TCP -LocalPort $Port -RemoteAddress 100.64.0.0/10 -Action Allow | Out-Null"
    }
    $fwFile = Join-Path $env:TEMP "shema_firewall.ps1"
    Set-Content -Path $fwFile -Value $fw -Encoding UTF8
    Say "עכשיו Windows ישאל אם לאשר שינוי (חלון כחול). זה פותח את הפורט $Port לטלפון שלך, רק ברשת הביתית הפרטית."
    try { Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$fwFile`"" }
    catch { Say "כלל חומת האש לא נוסף (האישור נדחה). הטלפון לא יוכל להתחבר עד שתריץ שוב את Install.bat ותאשר." "Warning" }
    Remove-Item $fwFile -ErrorAction SilentlyContinue
    $pub = Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object { $_.NetworkCategory -eq "Public" -and $_.InterfaceAlias -notlike "*Tailscale*" }
    if ($pub) {
        Say ("הרשת '$($pub[0].Name)' מוגדרת ב-Windows כציבורית, ולכן הטלפון לא יוכל להתחבר. אם זו הרשת של הבית: " +
             "הגדרות ← רשת ואינטרנט ← Wi-Fi (או Ethernet) ← מאפיינים ← סוג פרופיל רשת: פרטית.") "Warning"
    }
    if (-not $ts) {
        Say ("Tailscale לא מותקן במחשב. בלעדיו הטלפון שולח הקלטות רק כשהוא בבית; מחוץ לבית הן נשמרות בטלפון ונשלחות כשחוזרים.`n`n" +
             "כדי לקבל הקלטות גם מבחוץ: התקן Tailscale (חינם) במחשב ובטלפון, התחבר לאותו חשבון, והרץ שוב את Install.bat.")
    }

    # background start at logon (no window)
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $act = New-ScheduledTaskAction -Execute $vpyw -Argument "-X utf8 `"$App\home_listener.py`"" -WorkingDirectory $App
    $trg = New-ScheduledTaskTrigger -AtLogOn -User $user
    $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    $pr = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $taskOk = $false
    try {
        Register-ScheduledTask -TaskName "Shema" -Action $act -Trigger $trg -Settings $set -Principal $pr -Force -ErrorAction Stop | Out-Null
        Start-ScheduledTask -TaskName "Shema"
        $taskOk = $true
    } catch {
        Write-Host "scheduled task failed ($_); using the Startup folder instead"
        $ws = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Startup")) "Shema server.lnk"))
        $lnk.TargetPath = $vpyw; $lnk.Arguments = "-X utf8 `"$App\home_listener.py`""; $lnk.WorkingDirectory = $App; $lnk.Save()
        Start-Process $vpyw -ArgumentList "-X utf8 `"$App\home_listener.py`"" -WorkingDirectory $App -WindowStyle Hidden
    }

    # "שמע" shortcut on the desktop and in the Start menu
    $icon = Join-Path $App "ui\shema.ico"
    $url = "[InternetShortcut]`r`nURL=http://localhost:$Port/home`r`nIconIndex=0`r`nIconFile=$icon`r`n"
    foreach ($dir in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
        try { [IO.File]::WriteAllText((Join-Path $dir "שמע.url"), $url, (New-Object Text.UTF8Encoding $false)) } catch { }
    }
}

# ------------------------------------------------------------------ done
$up = $false
if (-not $Test) {
    for ($i = 0; $i -lt 40 -and -not $up; $i++) {
        try { Invoke-RestMethod "http://127.0.0.1:$Port/home/api/status" -TimeoutSec 3 | Out-Null; $up = $true } catch { Start-Sleep 2 }
    }
}
try { Stop-Transcript | Out-Null } catch { }
if ($Test) { Write-Host "TEST INSTALL DONE: $ShemaHome"; exit 0 }
$speed = if ($device -eq "cuda") { "תמלול על כרטיס המסך ($gpuName)." } else { "תמלול על המעבד: איטי יותר, ההקלטות מתעדכנות לאורך היום." }
if ($up) {
    Say ("שמע מותקן ופועל ברקע. $speed`n`n" +
         "עכשיו ייפתח המסך של שמע עם QR:`n" +
         "1. מורידים לטלפון את האפליקציה (QR קטן או הקישור שבמסך) ומתקינים.`n" +
         "2. באפליקציה: 'חבר למחשב' וסורקים את ה-QR הגדול.`n" +
         "3. באפליקציה: 'ללמד את הקול שלי' (25 שניות).`n`n" +
         "הסמל 'שמע' בשולחן העבודה פותח את המסך בכל פעם.")
    Start-Process "http://localhost:$Port/home#pair"
} else {
    Say "ההתקנה הסתיימה אבל השרת עוד לא עונה. נסה בעוד דקה את הסמל 'שמע' בשולחן העבודה. אם זה לא עובד: $ShemaHome\data\listener.log" "Warning"
}
