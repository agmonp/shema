# Shema - one-click update from the PC screen ("update" button). Started by the server itself, detached, after it
# downloaded and unpacked a release; the server it updates is stopped here and started again at the end.
# Only what an update needs: program files (with a backup), Python packages when requirements.txt changed, an import
# check, restart. On any failure the previous program files come back. Recordings, settings and models are untouched.
# (The full Install.bat stays for first installs and for releases that need new programs or models.)
#   powershell -File update.ps1 -Src <unpacked release> [-ShemaHome DIR] [-Port 8770] [-Python EXE]
param(
    [Parameter(Mandatory = $true)][string]$Src,
    [string]$ShemaHome = "",
    [int]$Port = 8770,
    [string]$Python = ""
)
$ErrorActionPreference = "Continue"
if (-not $ShemaHome) { $ShemaHome = Join-Path $env:LOCALAPPDATA "Shema" }
$App = Join-Path $ShemaHome "app"
$Prev = Join-Path $ShemaHome "app.prev"
$Data = Join-Path $ShemaHome "data"
$Result = Join-Path $Data "update_result.json"
$vpy = if ($Python) { $Python } else { Join-Path $ShemaHome "venv\Scripts\python.exe" }
$vpyw = Join-Path (Split-Path $vpy) "pythonw.exe"
if (-not (Test-Path $vpyw)) { $vpyw = $vpy }
try { Start-Transcript -Path (Join-Path $ShemaHome "update.log") -Append | Out-Null } catch { }
$new = ""
try { $new = (Get-Content (Join-Path $Src "server\VERSION") -ErrorAction Stop | Select-Object -First 1).Trim() } catch { }
$old = ""
try { $old = (Get-Content (Join-Path $App "VERSION") -ErrorAction Stop | Select-Object -First 1).Trim() } catch { }
Write-Host "update $old -> $new from $Src"

function Done([bool]$ok, [string]$msg) {
    $o = @{ ok = $ok; msg = $msg; from = $old; to = $new; at = (Get-Date).ToString("s") } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText($Result, $o, (New-Object Text.UTF8Encoding $false))
    Write-Host "DONE ok=$ok $msg"
    try { Stop-Transcript | Out-Null } catch { }
    exit ([int](-not $ok))
}

function Start-Server {
    $t = $null
    try { $t = Get-ScheduledTask -TaskName "Shema" -ErrorAction Stop } catch { }
    $mine = $t -and ($t.Actions | Where-Object { $_.Arguments -like "*$App\home_listener.py*" })
    if ($mine) { Start-ScheduledTask -TaskName "Shema"; Write-Host "started the Shema task" }
    else {
        $env:SHEMA_HOME = $ShemaHome; $env:HOME_PORT = "$Port"                    # a task does not pass the server's own settings
        Start-Process $vpyw -ArgumentList "-X utf8 `"$App\home_listener.py`"" -WorkingDirectory $App -WindowStyle Hidden; Write-Host "started $vpyw" }
}

function Wait-Server([string]$want) {
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $s = Invoke-RestMethod "http://127.0.0.1:$Port/home/api/status" -TimeoutSec 3
            if (-not $want -or $s.version -eq $want) { return $true }
        } catch { }
        Start-Sleep 2
    }
    return $false
}

function Stop-Server {
    $t = $null
    try { $t = Get-ScheduledTask -TaskName "Shema" -ErrorAction Stop } catch { }
    if ($t -and ($t.Actions | Where-Object { $_.Arguments -like "*$App\home_listener.py*" })) {
        Stop-ScheduledTask -TaskName "Shema"                                       # the task first, so it does not restart it
    }
    for ($i = 0; $i -lt 10; $i++) {
        $p = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine -like "*$App\home_listener.py*" }
        if (-not $p) { return }
        $p | ForEach-Object { Write-Host "stopping pid $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep 1
    }
}

function Roll-Back([string]$why) {
    Write-Host "rolling back: $why"
    Stop-Server
    if (Test-Path (Join-Path $Prev "home_listener.py")) { & robocopy $Prev $App /MIR /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null }
    Start-Server
    Wait-Server "" | Out-Null
    Done $false $why
}

if (-not $new -or -not (Test-Path (Join-Path $Src "server\home_listener.py"))) { Done $false "the downloaded package is not a Shema release" }
if (-not (Test-Path (Join-Path $App "home_listener.py"))) { Done $false "no installed Shema in $App (use Install.bat)" }

# 1. stop the running server
Stop-Server

# 2. backup, then the new program files
& robocopy $App $Prev /MIR /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Start-Server; Done $false "could not back up the program files" }
& robocopy (Join-Path $Src "server") $App /MIR /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Roll-Back "could not copy the new program files" }
foreach ($f in "uninstall.ps1", "Uninstall.bat") {
    $s = Join-Path $Src "install\$f"
    if (Test-Path $s) { Copy-Item $s (Join-Path $ShemaHome $f) -Force }
}

# 3. Python packages, only when the list changed
$req = Join-Path $Src "requirements.txt"
$shaFile = Join-Path $ShemaHome "requirements.sha"
if (Test-Path $req) {
    $sha = (Get-FileHash $req -Algorithm SHA256).Hash
    $had = if (Test-Path $shaFile) { (Get-Content $shaFile | Select-Object -First 1).Trim() } else { "" }
    if ($sha -ne $had) {
        Write-Host "requirements changed: pip install"
        & $vpy -m pip install --disable-pip-version-check -q -r $req
        if ($LASTEXITCODE -ne 0) { Roll-Back "installing Python packages failed" }
        Set-Content -Path $shaFile -Value $sha
    }
}

# 4. does the new code load at all?
$env:PYTHONPATH = ""
# (the exit code, not the text: PowerShell 5 copies the command line, with any marker in it, into the error output)
$chk = & $vpy -X utf8 -c "import sys; sys.path.insert(0, r'$App'); import home_listener" 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { Write-Host $chk; Roll-Back "the new version does not start on this PC" }

# 5. start it and wait for it to answer with the new version
Start-Server
if (-not (Wait-Server $new)) { Roll-Back "the new version did not answer" }
Done $true "updated"
