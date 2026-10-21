param([Parameter(Mandatory=$true)][string]$File, [switch]$VerifyOnly, [switch]$NativeOnly)
$ErrorActionPreference = 'Stop'
if ($NativeOnly -and -not $VerifyOnly) { throw 'NativeOnly solo se permite para verificación en el equipo limpio.' }
if ((-not $NativeOnly -and (-not $env:SIGNTOOL_PATH -or -not $env:SIGN_CERT_SHA1)) -or -not $env:SIGN_CERT_SHA256 -or -not $env:SIGN_EXPECTED_SUBJECT) {
    throw 'Falta SIGNTOOL_PATH, SIGN_CERT_SHA1, SIGN_CERT_SHA256 o SIGN_EXPECTED_SUBJECT. No se permite degradar una release a sin firma.'
}
if ((-not $NativeOnly -and $env:SIGN_CERT_SHA1 -notmatch '^[A-Fa-f0-9]{40}$') -or $env:SIGN_CERT_SHA256 -notmatch '^[A-Fa-f0-9]{64}$') { throw 'Huella de certificado inválida.' }
$resolved = (Resolve-Path -LiteralPath $File).Path
if (-not $VerifyOnly) {
    $timestamp = $env:SIGN_TIMESTAMP_URL
    if (-not $timestamp) { $timestamp = 'http://timestamp.digicert.com' }
    # SHA1 here selects the certificate, never the file digest algorithm.
    & $env:SIGNTOOL_PATH sign /sha1 $env:SIGN_CERT_SHA1 /s My /fd SHA256 /tr $timestamp /td SHA256 $resolved
    if ($LASTEXITCODE -ne 0) { throw 'Authenticode signing or RFC 3161 timestamp failed.' }
}
if (-not $NativeOnly) {
    & $env:SIGNTOOL_PATH verify /pa /all /v $resolved
    if ($LASTEXITCODE -ne 0) { throw "SignTool verification failed: $resolved" }
}
$signature = Get-AuthenticodeSignature -LiteralPath $resolved
if ($signature.Status -ne 'Valid' -or -not $signature.TimeStamperCertificate) { throw 'Firma o timestamp ausente/no confiable.' }
$hasher = [System.Security.Cryptography.SHA256]::Create()
try { $thumb = [BitConverter]::ToString($hasher.ComputeHash($signature.SignerCertificate.RawData)).Replace('-','') }
finally { $hasher.Dispose() }
if ($thumb -ne $env:SIGN_CERT_SHA256 -or $signature.SignerCertificate.Subject -cne $env:SIGN_EXPECTED_SUBJECT) { throw 'Identidad del editor inesperada.' }
# WinVerifyTrust/SignTool validate signature, chain, revocation and timestamp.
# Inspect the PE certificate record too: require SHA-256 CMS and RFC 3161 OID.
Add-Type -AssemblyName System.Security
$bytes = [IO.File]::ReadAllBytes($resolved)
$pe = [BitConverter]::ToInt32($bytes, 0x3c)
$optional = $pe + 24
$magic = [BitConverter]::ToUInt16($bytes, $optional)
$dataOffset = if ($magic -eq 0x20b) { 112 } elseif ($magic -eq 0x10b) { 96 } else { throw 'PE inválido' }
$certificateOffset = [BitConverter]::ToInt32($bytes, $optional + $dataOffset + 32)
$length = [BitConverter]::ToInt32($bytes, $certificateOffset)
if ($certificateOffset -le 0 -or $length -le 8 -or $certificateOffset + $length -gt $bytes.Length) { throw 'Registro Authenticode inválido.' }
$cms = New-Object System.Security.Cryptography.Pkcs.SignedCms
$payload = New-Object byte[] ($length - 8)
[Array]::Copy($bytes, $certificateOffset + 8, $payload, 0, $payload.Length)
$cms.Decode($payload)
foreach ($signer in $cms.SignerInfos) {
    if ($signer.DigestAlgorithm.Value -ne '2.16.840.1.101.3.4.2.1') { throw 'Digest Authenticode no es SHA-256.' }
    if (-not ($signer.UnsignedAttributes | Where-Object { $_.Oid.Value -eq '1.3.6.1.4.1.311.3.3.1' })) { throw 'Falta timestamp RFC 3161.' }
}
