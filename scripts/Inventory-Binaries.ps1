param([Parameter(Mandatory=$true)][string]$Bundle, [switch]$Production)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Bundle).Path
$inventory = foreach ($file in Get-ChildItem -LiteralPath $root -File -Recurse | Where-Object { $_.Extension -in '.dll','.pyd','.exe' }) {
    $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
    if ($Production -and $signature.SignerCertificate -and $signature.Status -ne 'Valid') { throw "Firma de tercero inválida: $($file.FullName)" }
    [ordered]@{ path=$file.FullName.Substring($root.Length + 1); sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash;
        signature_status=[string]$signature.Status; signer=if ($signature.SignerCertificate) {$signature.SignerCertificate.Subject} else {$null};
        timestamp= [bool]$signature.TimeStamperCertificate }
}
$inventory | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $root 'native-inventory.json') -Encoding UTF8
