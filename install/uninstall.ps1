# Shema (שמע) -- uninstall the PC side. Removes the background task, the firewall rules, the program, the Python
# environment, the models and the shortcuts. ASKS before deleting your data (recordings, transcripts, voices).
# Python, ffmpeg, Ollama and Tailscale stay installed (other programs may use them): remove them in Settings > Apps.
param([string]$ShemaHome = "", [switch]$Quiet)
$ErrorActionPreference = "Continue"
if (-not $ShemaHome) { $ShemaHome = Join-Path $env:LOCALAPPDATA "Shema" }
$RTL = 0x180000
$forms = $false
try { Add-Type -AssemblyName System.Windows.Forms; $forms = $true } catch { }
function Ask([string]$text) {
    Write-Host $text
    if ($Quiet) { return $false }
    if ($forms) { return ([System.Windows.Forms.MessageBox]::Show($text, "שמע", "YesNo", "Question", "Button2", $RTL) -eq "Yes") }
    return ((Read-Host "y/n") -match '^(y|yes)')
}

if (-not (Ask "להסיר את שמע מהמחשב? (בשלב הבא תישאל לגבי ההקלטות והנתונים)")) { exit 0 }

Write-Host "Stopping the server ..."
try { Stop-ScheduledTask -TaskName "Shema" -ErrorAction Stop } catch { }
try { Unregister-ScheduledTask -TaskName "Shema" -Confirm:$false -ErrorAction Stop } catch { }
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$ShemaHome\app\home_listener.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 2

Write-Host "Removing the firewall rules (Windows asks for permission) ..."
if (Get-NetFirewallRule -Group "Shema" -ErrorAction SilentlyContinue) {
    try { Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile -Command Remove-NetFirewallRule -Group 'Shema'" }
    catch { Write-Host "firewall rules not removed (permission declined)" }
}

Write-Host "Removing shortcuts, program, Python environment and models ..."
foreach ($p in @((Join-Path ([Environment]::GetFolderPath("Desktop")) "שמע.url"), (Join-Path ([Environment]::GetFolderPath("Programs")) "שמע.url"),
                 (Join-Path ([Environment]::GetFolderPath("Startup")) "Shema server.lnk"))) { Remove-Item -LiteralPath $p -ErrorAction SilentlyContinue }
foreach ($d in "venv", "app", "models") { Remove-Item -LiteralPath (Join-Path $ShemaHome $d) -Recurse -Force -ErrorAction SilentlyContinue }
Remove-Item -LiteralPath (Join-Path $ShemaHome "app.apk") -ErrorAction SilentlyContinue

$data = Join-Path $ShemaHome "data"
if (Test-Path $data) {
    $mb = [math]::Round(((Get-ChildItem $data -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum) / 1MB)
    if (Ask "למחוק גם את הנתונים? הקלטות, תמלולים, סיכומים וקולות שלימדת ($mb MB, בתיקייה $data).`n`nאי אפשר לשחזר אחרי מחיקה. 'לא' משאיר אותם במקום.") {
        Remove-Item -LiteralPath $data -Recurse -Force
        Write-Host "data deleted"
    } else { Write-Host "data kept in $data" }
}
Write-Host "Done. The phone app: long-press the 'שמע' icon on the phone > Uninstall."
