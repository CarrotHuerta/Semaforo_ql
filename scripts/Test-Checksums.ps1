param([Parameter(Mandatory=$true)][string]$Directory, [switch]$Production)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Directory).Path
$lines = Get-Content -LiteralPath (Join-Path $root 'SHA256SUMS.txt')
$seen = @{}
foreach ($line in $lines) {
    if ($line -notmatch '^([a-fA-F0-9]{64})  (SemaforoIA-[0-9]+\.[0-9]+\.[0-9]+-windows-x64(?:-dev)?-(?:setup\.exe|portable\.zip))$') { throw 'Formato de checksum no válido.' }
    $expected, $name = $matches[1], $matches[2]
    if ($seen.ContainsKey($name) -or ($Production -and $name.Contains('-dev-'))) { throw 'Artefactos duplicados o canal incorrecto.' }
    $seen[$name] = $true
    $target = Join-Path $root $name
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $expected) { throw "Checksum incorrecto: $name" }
}
if ($seen.Count -ne 2) { throw 'Se requieren exactamente instalador y portable.' }
$stems = @($seen.Keys | ForEach-Object { $_ -replace '-(setup\.exe|portable\.zip)$', '' } | Select-Object -Unique)
if ($stems.Count -ne 1) { throw 'El instalador y portable deben ser de la misma version y canal.' }
Write-Output 'SHA256SUMS verificado.'
