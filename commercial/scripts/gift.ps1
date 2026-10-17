# Issue a free "שמע Pro" gift code locked to one phone.
#
# The friend opens Shema Pro -> the Pro pill at the top -> "יש לי קוד מתנה", and sends you the phone code
# shown there (8 letters, e.g. K7Q2-M9XD). Then:
#   powershell -File gift.ps1 -Phone K7Q2-M9XD -Name "דנה"            (forever)
#   powershell -File gift.ps1 -Phone K7Q2-M9XD -Name "דנה" -Days 365  (for a year)
# The message to send back is printed and copied to the clipboard; every gift is logged in shema-gifts.csv.
#
# The code is signed with the private key in C:\Users\agmon\keys (never in the repository; back it up with the
# release keystore). The app holds only the public key (Gift.kt), so the repository being public does not matter.
# -NewKey creates the key once and prints the public key to put in Gift.kt.
param(
    [string]$Phone = "",
    [string]$Name = "",
    [int]$Days = 0,
    [int]$UntilDay = 0,          # last day as days since 1970 (the dashboard's exact date); overrides -Days
    [switch]$Json,               # for the dashboard: print {"code","until"} only, no clipboard, no log
    [switch]$NewKey,
    [string]$KeyFile = "$env:USERPROFILE\keys\shema-gift-key.json"
)
$ErrorActionPreference = "Stop"
$alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"          # Crockford base32: no I, L, O, U
$curve = [System.Security.Cryptography.ECCurve+NamedCurves]::nistP256
$sha = [System.Security.Cryptography.HashAlgorithmName]::SHA256
# X.509 SubjectPublicKeyInfo header of a P-256 uncompressed point (what Java's X509EncodedKeySpec reads)
$spkiHead = [byte[]](0x30,0x59,0x30,0x13,0x06,0x07,0x2a,0x86,0x48,0xce,0x3d,0x02,0x01,0x06,0x08,0x2a,0x86,0x48,0xce,0x3d,0x03,0x01,0x07,0x03,0x42,0x00,0x04)

function To-B32([byte[]]$b) {
    $out = New-Object System.Text.StringBuilder; $acc = 0; $bits = 0
    foreach ($x in $b) {
        $acc = (($acc -shl 8) -bor $x) -band 0xFFFF; $bits += 8
        while ($bits -ge 5) { $bits -= 5; [void]$out.Append($alphabet[($acc -shr $bits) -band 31]) }
    }
    if ($bits -gt 0) { [void]$out.Append($alphabet[($acc -shl (5 - $bits)) -band 31]) }
    $out.ToString()
}
function From-B32([string]$s) {
    $s = $s.ToUpper().Replace("O", "0").Replace("I", "1").Replace("L", "1") -replace "[^0-9A-Z]", ""
    $out = New-Object System.Collections.Generic.List[byte]; $acc = 0; $bits = 0
    foreach ($ch in $s.ToCharArray()) {
        $v = $alphabet.IndexOf($ch); if ($v -lt 0) { throw "Bad character '$ch' in the phone code" }
        $acc = (($acc -shl 5) -bor $v) -band 0xFFFF; $bits += 5
        if ($bits -ge 8) { $bits -= 8; $out.Add([byte](($acc -shr $bits) -band 0xFF)) }
    }
    $out.ToArray()
}

if ($NewKey) {
    if (Test-Path $KeyFile) { throw "$KeyFile already exists. Codes already given out depend on it; not replacing it." }
    $ec = [System.Security.Cryptography.ECDsa]::Create($curve)
    $p = $ec.ExportParameters($true)
    New-Item -ItemType Directory -Force (Split-Path $KeyFile) | Out-Null
    @{ D = [Convert]::ToBase64String($p.D); X = [Convert]::ToBase64String($p.Q.X); Y = [Convert]::ToBase64String($p.Q.Y) } |
        ConvertTo-Json | Set-Content -Encoding ascii $KeyFile
    Write-Host "Key saved to $KeyFile (back it up)."
    Write-Host "Public key for Gift.kt:"
    Write-Host ([Convert]::ToBase64String($spkiHead + $p.Q.X + $p.Q.Y))
    return
}

if (-not (Test-Path $KeyFile)) { throw "No key at $KeyFile (restore it from the backup; -NewKey only for a brand-new app)" }
$phoneBytes = From-B32 $Phone
if ($phoneBytes.Length -ne 5) { throw "The phone code is 8 letters/digits, like K7Q2-M9XD" }
$k = Get-Content -Raw $KeyFile | ConvertFrom-Json
$params = New-Object System.Security.Cryptography.ECParameters
$q = New-Object System.Security.Cryptography.ECPoint
$q.X = [Convert]::FromBase64String($k.X); $q.Y = [Convert]::FromBase64String($k.Y)
$params.Curve = $curve; $params.Q = $q; $params.D = [Convert]::FromBase64String($k.D)
$ec = [System.Security.Cryptography.ECDsa]::Create($params)

# payload: version 1 | phone (5 bytes) | last day (days since 1970, 2 bytes, 0 = forever) | name (UTF-8)
$until = 0
if ($Days -gt 0) { $until = [int][Math]::Floor(((Get-Date).ToUniversalTime().AddDays($Days) - [datetime]'1970-01-01').TotalDays) }
if ($UntilDay -gt 0) { $until = $UntilDay }
$nameBytes = [System.Text.Encoding]::UTF8.GetBytes($Name.Trim())
if ($nameBytes.Length -gt 60) { throw "Name too long" }
$payload = [byte[]](@(1) + $phoneBytes + @([byte](($until -shr 8) -band 0xFF), [byte]($until -band 0xFF)) + $nameBytes)
$signed = [System.Text.Encoding]::ASCII.GetBytes("shema-gift-v1") + $payload
$sig = $ec.SignData([byte[]]$signed, $sha)                 # IEEE P1363 r||s, 64 bytes
$code = "SHEMA-" + (To-B32 ([byte[]]($payload + $sig)))
if ($Json) { Write-Output ('{"code":"' + $code + '","until":' + $until + '}'); return }

# one message: the app pulls the SHEMA-... code out of whatever the friend copied
$when = if ($Days -gt 0) { "עד " + (Get-Date).AddDays($Days).ToString("dd/MM/yyyy") } else { "ללא הגבלת זמן" }
$msg = "🎁 שמע Pro במתנה ($when)`n" +
    "1. העתק את כל ההודעה הזו (לחיצה ארוכה ← העתק).`n" +
    "2. בשמע Pro: התג למעלה ← יש לי קוד מתנה ← הפעל.`n" +
    "הקוד עובד רק בטלפון שלך.`n`n" + $code
Set-Clipboard -Value $msg
Write-Host $code
Write-Host ""
Write-Host "The message for $Phone is on the clipboard: paste it into WhatsApp."

$log = Join-Path (Split-Path $KeyFile) "shema-gifts.csv"
[pscustomobject]@{ date = (Get-Date).ToString("yyyy-MM-dd HH:mm"); name = $Name; phone = $Phone.ToUpper(); days = $Days } |
    Export-Csv -Append -NoTypeInformation -Encoding UTF8 $log
